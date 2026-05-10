# Application Architecture — Braiins Hashpower MCP Server

**Version:** 0.2  
**Document Type:** Architecture Decision Record + System Design  
**Scope:** Multi-tenant, horizontally scalable production deployment  
**Last Updated:** 2026-05-09

---

## 1. Executive Summary

This document describes the production architecture for `braiins-hashpower-mcp`, a multi-tenant MCP server exposing the Braiins Hashpower Network spot-market API to AI agents over SSE transport. The architecture is designed for horizontal scaling, tenant isolation, stateless compute nodes, and operator-grade observability — while preserving the safety guarantees (dry_run gates, spend caps, unit normalization) defined in SPEC.md.

The core design decision is: **the MCP server nodes are stateless**. All session state, tenant config, and caching live in shared infrastructure (Redis, PostgreSQL) rather than in-process. This enables N replicas behind a load balancer with no sticky sessions required.

---

## 2. High-Level Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │               Clients / Consumers               │
                        │  ┌────────────┐  ┌──────────────┐  ┌────────┐  │
                        │  │  LangGraph │  │ Claude / Curs│  │ Custom │  │
                        │  │   Agents   │  │     or       │  │ Agent  │  │
                        │  └─────┬──────┘  └──────┬───────┘  └───┬────┘  │
                        └────────┼────────────────┼──────────────┼────────┘
                                 │                │              │
                         SSE transport (MCP protocol, per-tenant Bearer token)
                                 │                │              │
                        ┌────────▼────────────────▼──────────────▼────────┐
                        │           API Gateway / Load Balancer            │
                        │  TLS termination  │  Auth header routing         │
                        │  Rate limiting    │  Tenant ID injection         │
                        │  (Traefik / NGINX / Kong)                        │
                        └────────────────────┬─────────────────────────────┘
                                             │ HTTP/2 (SSE)
                        ┌────────────────────▼─────────────────────────────┐
                        │            MCP Server Pool (stateless)           │
                        │  ┌──────────────┐  ┌──────────────┐              │
                        │  │  mcp-node-1  │  │  mcp-node-2  │  ... N nodes │
                        │  │  FastMCP+SSE │  │  FastMCP+SSE │              │
                        │  │  Uvicorn     │  │  Uvicorn     │              │
                        │  └──────┬───────┘  └──────┬───────┘              │
                        └─────────┼─────────────────┼────────────────────  ┘
                                  │                  │
            ┌─────────────────────┼──────────────────┼──────────────────────┐
            │                     │   Shared State   │                      │
            │   ┌─────────────────▼──────────────────▼───────────────┐      │
            │   │                Redis Cluster                        │      │
            │   │  • /spot/settings cache (per-tenant TTL)            │      │
            │   │  • Rate-limit counters (per-tenant, per-tool)       │      │
            │   │  • Session token store                              │      │
            │   │  • Idempotency key store (client_order_id)          │      │
            │   └─────────────────────────────────────────────────────┘      │
            │                                                                 │
            │   ┌─────────────────────────────────────────────────────┐      │
            │   │              PostgreSQL (RDS / Cloud SQL)           │      │
            │   │  • Tenant registry (id, api_key_hash, mode, limits) │      │
            │   │  • Audit log (every tool call, tenant, outcome)     │      │
            │   │  • Order history (enriched, denormalized)           │      │
            │   └─────────────────────────────────────────────────────┘      │
            └─────────────────────────────────────────────────────────────────┘
                                  │
            ┌─────────────────────▼──────────────────────────────────────────┐
            │                 Braiins API Proxy (optional)                   │
            │   Shared outbound HTTP connection pool + circuit breaker       │
            │   One pool per Braiins API credential set (per tenant)         │
            └─────────────────────┬──────────────────────────────────────────┘
                                  │ HTTPS REST
            ┌─────────────────────▼──────────────────────────────────────────┐
            │            Braiins Hashpower Network API                       │
            │            https://hashpower.braiins.com/api/                  │
            └────────────────────────────────────────────────────────────────┘
```

---

## 3. Multi-Tenancy Model

### 3.1 Tenant Identity

Each tenant is identified by a **bearer token** sent in the `Authorization: Bearer <token>` header on every SSE connection request. The API gateway validates and enriches the request with a `X-Tenant-Id` header before forwarding to MCP nodes.

Tenant records are stored in PostgreSQL:

```sql
CREATE TABLE tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    api_key_hash    TEXT NOT NULL,          -- bcrypt hash of bearer token
    braiins_api_key TEXT NOT NULL,          -- encrypted at rest
    braiins_secret  TEXT NOT NULL,          -- encrypted at rest
    mode            TEXT DEFAULT 'read_only', -- read_only | trading
    dry_run_default BOOLEAN DEFAULT true,
    max_order_usd   NUMERIC DEFAULT 500,
    rate_limit_rpm  INTEGER DEFAULT 60,     -- requests per minute
    created_at      TIMESTAMPTZ DEFAULT now(),
    is_active       BOOLEAN DEFAULT true
);
```

### 3.2 Tenant Isolation

| Isolation Concern | Mechanism |
|-------------------|-----------|
| API credentials | Per-tenant Braiins API key/secret, encrypted at rest in PostgreSQL |
| Settings cache | Redis key: `tenant:{id}:spot:settings` with per-tenant TTL |
| Rate limits | Redis counter: `ratelimit:{id}:{tool}:{window}` |
| Audit trail | Every tool call logged with `tenant_id` in PostgreSQL |
| Spend caps | Per-tenant `max_order_usd` enforced in `safety/limits.py` |
| Order idempotency | Redis key: `idempotency:{id}:{client_order_id}` with 24h TTL |

### 3.3 Credential Storage

Braiins API credentials are stored encrypted in PostgreSQL using AES-256-GCM with a key stored in a secrets manager (AWS Secrets Manager / HashiCorp Vault). MCP nodes decrypt credentials at request time using the injected `X-Tenant-Id`, never holding them in memory beyond a single request.

```
Tenant Request
     │
     ▼
API Gateway validates Bearer token → resolves tenant_id → injects X-Tenant-Id
     │
     ▼
MCP Node reads tenant_id from request header
     │
     ▼
TenantConfigLoader.get(tenant_id)
  → PostgreSQL lookup (cached in Redis: `tenant:{id}:config`, 5min TTL)
  → Decrypt Braiins credentials using KMS
     │
     ▼
BraiinsClient(api_key, secret).call(...)
```

---

## 4. Stateless MCP Nodes

### 4.1 Design Principle

MCP server nodes hold **no durable state**. Every node can handle every request. This enables:

- Horizontal autoscaling (add/remove nodes without draining sessions).
- Zero-downtime deployments (rolling restart).
- No sticky session requirements in the load balancer.

SSE connections are long-lived HTTP streams. When a client reconnects (e.g., after a node restart), the API gateway routes it to any available healthy node — the new node reconstructs context from Redis/PostgreSQL on demand.

### 4.2 State Distribution

| State Type | Location | TTL / Retention |
|------------|----------|-----------------|
| Spot settings cache | Redis | 60s |
| Tenant config cache | Redis | 5 min |
| Rate limit counters | Redis | Sliding 60s window |
| Idempotency keys | Redis | 24h |
| Session tokens | Redis | Connection lifetime + 30s |
| Audit log | PostgreSQL | 90 days |
| Order history | PostgreSQL | Indefinite |
| Application metrics | Prometheus / OTEL Collector | 30 days |

### 4.3 Settings Cache Architecture

`/spot/settings` is the most-read endpoint (every order validation requires it). To prevent thundering herd on cache miss under high traffic:

```python
# settings_cache.py
class SettingsCache:
    """
    Tenant-scoped Redis cache with probabilistic early expiry
    to prevent simultaneous cache misses across nodes.
    """
    async def get(self, tenant_id: str) -> SpotSettings:
        key = f"tenant:{tenant_id}:spot:settings"
        cached = await redis.get(key)
        if cached:
            return SpotSettings.model_validate_json(cached)
        # Distributed lock prevents multiple nodes racing to refresh
        async with redis_lock(f"lock:{key}", timeout=5):
            # Re-check after acquiring lock
            cached = await redis.get(key)
            if cached:
                return SpotSettings.model_validate_json(cached)
            settings = await braiins_client.get_settings()
            await redis.setex(key, TTL_SECONDS, settings.model_dump_json())
            return settings
```

---

## 5. SSE Transport at Scale

### 5.1 Connection Model

Each `langchain-mcp-adapters` client opens an SSE connection per tool invocation by default. Under high-agent-concurrency, this creates a connection-per-call pattern. The architecture accounts for this:

- **Uvicorn workers per node:** `workers = 2 * CPU_cores + 1` (async, not threaded).
- **Nginx/Traefik upstream:** `keepalive 100` — reuse TCP connections across SSE streams.
- **Max concurrent SSE streams per node:** configurable via `MAX_CONNECTIONS_PER_NODE` (default 500).
- **Backpressure:** return HTTP 503 with `Retry-After` header when at capacity; load balancer retries to next healthy node.

### 5.2 Load Balancer Configuration (Traefik example)

```yaml
# traefik/dynamic.yml
http:
  services:
    mcp-pool:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 10s
          timeout: 3s
        sticky: false          # No sticky sessions needed (stateless nodes)
        servers:
          - url: "http://mcp-node-1:8765"
          - url: "http://mcp-node-2:8765"

  middlewares:
    tenant-auth:
      forwardAuth:
        address: "http://auth-service:8080/validate"
        authResponseHeaders:
          - "X-Tenant-Id"
    rate-limit:
      rateLimit:
        average: 60
        burst: 20
```

### 5.3 Handling SSE Reconnects

When a client reconnects after a node failure:

1. The `MultiServerMCPClient` in `langchain-mcp-adapters` retries the SSE connection automatically (exponential backoff).
2. The new node receives the initial MCP `initialize` handshake and reconstructs tool/resource/prompt listings from code (they are static).
3. In-flight tool calls that were interrupted return an error to the agent; the agent retries per its own retry logic.
4. No in-flight state is lost from the server side because nodes are stateless.

---

## 6. API Gateway and Auth

### 6.1 Gateway Responsibilities

| Responsibility | Implementation |
|----------------|----------------|
| TLS termination | Traefik / NGINX with Let's Encrypt or ACM certs |
| Bearer token validation | Forwarded to `auth-service` via `forwardAuth` |
| `X-Tenant-Id` injection | Set by auth-service on validated requests |
| Rate limiting (global) | Gateway-level token bucket (Traefik middleware) |
| Rate limiting (per-tenant) | MCP node reads Redis counter per tool call |
| Request logging | Structured JSON access log → log aggregator |
| Health routing | Remove unhealthy nodes from pool automatically |

### 6.2 Auth Service

A lightweight FastAPI service that:

1. Accepts `Authorization: Bearer <token>` header.
2. Looks up `bcrypt_verify(token, tenants.api_key_hash)` in PostgreSQL (with Redis token cache, 5min TTL).
3. Returns `200 + X-Tenant-Id: <uuid>` on success, `401` on failure.
4. Returns `403` if `tenants.is_active = false`.

The auth service is **not** in the MCP server process. It is a sidecar that the gateway calls on every request. MCP nodes trust the injected `X-Tenant-Id` header because they only receive traffic that has already passed gateway auth.

---

## 7. Data Layer

### 7.1 PostgreSQL Schema (key tables)

```sql
-- Tenant registry
CREATE TABLE tenants ( ... );  -- defined in section 3.1

-- Audit log (append-only, partitioned by month)
CREATE TABLE audit_log (
    id              BIGSERIAL,
    tenant_id       UUID REFERENCES tenants(id),
    tool_name       TEXT NOT NULL,
    input_json      JSONB,
    output_json     JSONB,
    success         BOOLEAN,
    error_message   TEXT,
    duration_ms     INTEGER,
    braiins_request_id TEXT,
    node_id         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);

-- Order mirror (enriched copy of Braiins order responses)
CREATE TABLE orders (
    id              UUID PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id),
    braiins_order_id TEXT NOT NULL,
    market          TEXT,
    amount          NUMERIC,
    price           NUMERIC,
    status          TEXT,
    client_order_id TEXT,
    dry_run         BOOLEAN,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
);
CREATE INDEX ON orders (tenant_id, status);
CREATE INDEX ON orders (tenant_id, created_at DESC);
```

### 7.2 Redis Key Schema

```
tenant:{tenant_id}:config             → JSON tenant record, 5min TTL
tenant:{tenant_id}:spot:settings      → JSON SpotSettings, 60s TTL
ratelimit:{tenant_id}:{tool}:{window} → integer counter, 60s sliding TTL
idempotency:{tenant_id}:{coid}        → JSON order result, 24h TTL
lock:tenant:{tenant_id}:spot:settings → distributed lock, 5s timeout
session:{connection_id}               → JSON session metadata, conn lifetime + 30s
```

---

## 8. Observability Stack

### 8.1 Metrics (Prometheus + Grafana)

Every MCP node exposes `/metrics` in Prometheus format. Key metrics:

```python
# metrics.py
from prometheus_client import Counter, Histogram, Gauge

tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total tool calls",
    ["tenant_id", "tool_name", "success"]
)
tool_duration_seconds = Histogram(
    "mcp_tool_duration_seconds",
    "Tool call duration",
    ["tenant_id", "tool_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)
active_sse_connections = Gauge(
    "mcp_active_sse_connections",
    "Active SSE connections",
    ["node_id"]
)
braiins_api_errors_total = Counter(
    "braiins_api_errors_total",
    "Braiins API errors",
    ["tenant_id", "status_code", "endpoint"]
)
orders_placed_total = Counter(
    "mcp_orders_placed_total",
    "Orders placed (live, non-dry-run)",
    ["tenant_id", "market"]
)
```

### 8.2 Structured Logging

All logs emitted as structured JSON using `structlog`:

```python
log.info(
    "tool_call",
    tenant_id=tenant_id,
    tool="create_bid",
    duration_ms=142,
    dry_run=True,
    success=True,
    braiins_request_id="abc123",
    node_id=NODE_ID,
)
```

Log pipeline: `structlog` → stdout → Fluent Bit → Loki or Elasticsearch.

### 8.3 Distributed Tracing (OpenTelemetry)

Every tool call is instrumented with an OTEL span:

```python
with tracer.start_as_current_span(
    "tool.create_bid",
    attributes={
        "tenant.id": tenant_id,
        "tool.name": "create_bid",
        "order.dry_run": dry_run,
        "order.market": market,
    }
) as span:
    result = await _execute_create_bid(...)
    span.set_attribute("order.success", result.success)
```

Trace pipeline: OTEL SDK → OTEL Collector → Tempo or Jaeger.

### 8.4 Alerting Rules

| Alert | Threshold | Severity |
|-------|-----------|----------|
| High tool error rate | >5% of calls failing over 5min window | Warning |
| Braiins API unavailable | >10 consecutive 5xx errors | Critical |
| SSE connections saturated | >90% of `MAX_CONNECTIONS_PER_NODE` | Warning |
| Tenant rate limit violations | >10 violations in 1min | Info |
| Live order placed (any) | Any `orders_placed_total` increment | Info (audit) |
| Settings cache miss spike | >20 cache misses/sec | Warning |

---

## 9. Deployment Architecture

### 9.1 Container Layout

```
docker-compose (dev) / Kubernetes (prod)

Services:
  mcp-server     (N replicas, stateless)
  auth-service   (2 replicas, stateless)
  redis          (Redis Cluster, 3 primary + 3 replica)
  postgres       (primary + read replica or RDS Multi-AZ)
  traefik        (2 replicas, HA)
  otel-collector (1 replica, sidecar pattern)
  prometheus     (1 replica + persistent volume)
  grafana        (1 replica + persistent volume)
```

### 9.2 Kubernetes Deployment Sketch

```yaml
# k8s/mcp-server-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: braiins-hashpower-mcp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: braiins-hashpower-mcp
  template:
    spec:
      containers:
        - name: mcp-server
          image: your-registry/braiins-hashpower-mcp:latest
          ports:
            - containerPort: 8765
          env:
            - name: MCP_SERVER_PORT
              value: "8765"
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: braiins-mcp-secrets
                  key: redis-url
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: braiins-mcp-secrets
                  key: database-url
            - name: KMS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: braiins-mcp-secrets
                  key: kms-key-id
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "1000m"
              memory: "512Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8765
            initialDelaySeconds: 5
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 8765
            initialDelaySeconds: 3
            periodSeconds: 5
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: braiins-hashpower-mcp-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: braiins-hashpower-mcp
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: mcp_active_sse_connections
        target:
          type: AverageValue
          averageValue: "400"
```

### 9.3 Health Endpoints

Every MCP node exposes:

| Endpoint | Purpose | Returns |
|----------|---------|---------|
| `GET /health` | Liveness (is the process running?) | `200 OK` or `503` |
| `GET /ready` | Readiness (can it handle traffic?) | `200` if Redis/PG reachable, else `503` |
| `GET /metrics` | Prometheus metrics scrape | Prometheus text format |

---

## 10. Security Model

### 10.1 Secrets Hierarchy

```
KMS (AWS KMS / Vault)
  └── Data Encryption Key (DEK) — rotated monthly
        └── Encrypts: tenant.braiins_api_key, tenant.braiins_secret
              └── Stored encrypted in PostgreSQL tenants table

Environment / Kubernetes Secrets
  └── DATABASE_URL
  └── REDIS_URL
  └── KMS_KEY_ID
  └── AUTH_SERVICE_SIGNING_KEY
```

### 10.2 Network Security

- MCP nodes are in a private subnet. Only the load balancer has a public IP.
- Auth service is accessible only from within the cluster.
- Redis and PostgreSQL are in a private subnet with security groups allowing only MCP node and auth service IPs.
- All inter-service communication inside the cluster uses mTLS (via Istio service mesh or Linkerd, optional for v0.2).

### 10.3 Input Validation

Every tool input passes through two validation layers:

1. **Pydantic schema validation** (automatic, in `schemas.py`): type checking, required fields, enum constraints.
2. **Business rule validation** (in `safety/validators.py`): unit bounds from cached settings, spend cap, market allowlist.

Validation failures return structured `MCPToolResponse(success=False, error=...)` — never raw Python exceptions.

### 10.4 Braiins API Credential Isolation

Each tenant has their own Braiins API credentials. The MCP server never co-mingles credentials:

- Tenant A's `create_bid` call uses Tenant A's Braiins key exclusively.
- No shared Braiins credential pool.
- Credential decryption occurs in `braiins/auth.py` and is scoped to the request lifecycle.

---

## 11. Scalability Analysis

### 11.1 Capacity Model (per node, conservative)

| Metric | Value | Basis |
|--------|-------|-------|
| Max concurrent SSE connections | 500 | Uvicorn async workers, 2 CPU cores |
| Tool calls/sec (read) | ~200 | 5ms avg latency, mostly Redis reads |
| Tool calls/sec (write) | ~50 | 20ms avg latency, Braiins API round-trip |
| Settings cache hit rate | >99% | 60s TTL, most workloads don't change settings |
| Redis ops/sec (per node) | ~1,000 | Cache reads + rate limit increments |

### 11.2 Scaling Triggers

- **Horizontal scale out:** CPU >70% or SSE connections >400/node → HPA adds nodes.
- **Redis:** Scale to Redis Cluster (3+ shards) at >50k ops/sec.
- **PostgreSQL:** Add read replica for audit log queries; write path scales with connection pooling (PgBouncer).
- **Braiins API rate limits:** If Braiins imposes per-key rate limits, implement tenant-aware token bucket in Redis to prevent API-level throttling.

### 11.3 Bottleneck Map

```
High agent concurrency
  → SSE connection count (mitigated: HPA)
  → Settings cache misses (mitigated: distributed lock refresh)
  → Braiins API rate limits (mitigated: per-tenant token bucket)

Bursty order placement
  → Spend cap enforcement latency (mitigated: Redis atomic incr)
  → Idempotency check latency (mitigated: Redis hash lookup)

Tenant config cold start
  → PostgreSQL lookup on first request (mitigated: Redis config cache, 5min TTL)
```

---

## 12. Disaster Recovery

| Scenario | Impact | Recovery |
|----------|--------|----------|
| MCP node failure | Clients reconnect via LB to healthy node in <5s | Zero data loss (stateless) |
| Redis node failure | Cache miss spike; settings re-fetched from Braiins API | Degraded latency for ~60s; no data loss |
| Redis cluster failure | All cache unavailable; rate limiting and idempotency disabled | Fail safe: all write tools return error until Redis restores |
| PostgreSQL failure | Tenant config unavailable; auth fails | All requests return 503; no data loss if replica promoted |
| Braiins API unavailable | All Braiins calls fail | Circuit breaker returns cached last-known data for reads; writes fail gracefully |

---

## 13. Development and Local Stack

```yaml
# docker-compose.dev.yml
services:
  mcp-server:
    build: .
    ports: ["8765:8765"]
    environment:
      - BRAIINS_MODE=read_only
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://postgres:postgres@postgres:5432/braiins_mcp
      - MCP_SINGLE_TENANT_MODE=true
      - SINGLE_TENANT_API_KEY=dev_key
    depends_on: [redis, postgres]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: braiins_mcp
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  prometheus:
    image: prom/prometheus
    volumes: ["./observability/prometheus.yml:/etc/prometheus/prometheus.yml"]
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
    volumes: ["./observability/dashboards:/etc/grafana/provisioning/dashboards"]
```

In `SINGLE_TENANT_MODE=true`, the auth layer is bypassed and a static dev API key is used, restoring the single-tenant behavior from SPEC.md v0.1.

---

## 14. Decision Log

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| Stateless MCP nodes | Enables horizontal scale without sticky sessions | Stateful WebSocket sessions (rejected: session affinity complexity) |
| Redis for cache + rate limiting | Low-latency, cluster-capable, atomic operations | In-process LRU cache (rejected: cache is per-node, not shared across replicas) |
| PostgreSQL for audit log | ACID, partitioning, SQL query for compliance review | ClickHouse (deferred to v0.3 for analytics scale) |
| Per-tenant Braiins credentials | Full isolation, no cross-tenant exposure | Shared service account (rejected: single account is a shared failure point) |
| SSE transport (primary) | Wide client support, headers, stateless-friendly | `streamable_http` only (deferred to v0.2 as secondary option) |
| Gateway-level auth (not in MCP node) | Separation of concerns; allows auth without modifying MCP protocol | In-process auth middleware (deferred as fallback) |
| `dry_run=true` default | Prevents accidental live orders from misconfigured agents | No default (rejected: too risky for automated agent context) |

---

## References

- [langchain-mcp-adapters — SSE + runtime headers](https://github.com/langchain-ai/langchain-mcp-adapters)
- [MCP Server Concepts — Tools, Resources, Prompts](https://modelcontextprotocol.io/docs/learn/server-concepts)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Braiins Hashpower API Reference](https://hashpower.braiins.com/api/)
- SPEC.md (this repository)
