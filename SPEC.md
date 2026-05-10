# SPEC.md — Braiins Hashpower MCP Server

**Version:** 0.2  
**Transport:** SSE (primary) + Streamable HTTP (v0.2)  
**Framework:** FastMCP (`mcp[server]>=1.9.1`) + LangChain MCP Adapters  
**API Target:** [Braiins Hashpower Network](https://hashpower.braiins.com/api/)  
**Language:** Python 3.11+  
**Deployment Model:** Multi-tenant, horizontally scalable, stateless nodes  
**Architecture Reference:** See ARCHITECTURE.md for full system design

---

## 1. Purpose and Scope

This document specifies the design of an MCP server that wraps the Braiins Hashpower Network spot-market REST API. The server exposes structured **tools**, **resources**, and **prompts** to AI agent clients (LangGraph agents, Claude, Cursor, etc.) via SSE transport.

### Goals

- Provide a safe, agent-friendly interface for reading Braiins spot-market data and managing orders.
- Enforce server-side unit normalization using `/spot/settings` metadata before any order is submitted.
- Support multi-tenant operation with full per-tenant credential and configuration isolation.
- Scale horizontally with stateless compute nodes; all shared state in Redis and PostgreSQL.
- Guarantee credentials never leave the server process.
- Default to `dry_run=true` on all write tools until explicitly disabled by the operator.
- Be compatible with `MultiServerMCPClient` from `langchain-mcp-adapters` over SSE.

### Out of Scope (v0.2)

- Futures or non-spot market types.
- Webhook or push-based order status notifications.
- Portfolio analytics or charting.

---

## 2. Transport: SSE

The server uses SSE (Server-Sent Events) as its primary transport. SSE is one of the two HTTP-based MCP transports supported by `langchain-mcp-adapters` (alongside `streamable_http`). SSE is chosen because:

- It is widely supported across MCP clients including Claude Desktop, Cursor, and LangGraph agents.
- The `langchain-mcp-adapters` `MultiServerMCPClient` supports it natively with `"transport": "sse"`.
- Runtime headers (e.g., `Authorization`, trace IDs) can be injected per-connection — a requirement for multi-tenant auth.
- It is stateless-friendly for horizontally scaled deployments.

`streamable_http` transport will be added as a secondary option in v0.2. The SSE endpoint is the v0.2 stable interface.

### Server Endpoint

```
GET http://{host}:{port}/sse
```

Default: `http://0.0.0.0:8765/sse`

Health and readiness endpoints (required for load balancer routing):

```
GET /health    → liveness check
GET /ready     → readiness check (Redis + PostgreSQL reachable)
GET /metrics   → Prometheus metrics scrape
```

### Client Configuration (`langchain-mcp-adapters`)

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "braiins": {
            "transport": "sse",
            "url": "http://localhost:8765/sse",
            "headers": {
                # Multi-tenant: per-tenant bearer token
                "Authorization": "Bearer <tenant_api_key>",
                # Optional: per-request trace ID for distributed tracing
                "X-Trace-Id": "optional-trace-header"
            }
        }
    }
)
tools = await client.get_tools()
```

> Only `sse` and `streamable_http` transports support runtime headers in `langchain-mcp-adapters`. The `Authorization` header is required for multi-tenant deployments; it is validated by the API gateway before reaching MCP nodes.

---

## 3. Multi-Tenancy

### 3.1 Tenant Identity and Isolation

Each tenant is identified by a bearer token resolved to a `tenant_id` (UUID) by the API gateway auth service. MCP nodes receive `X-Tenant-Id` on every validated request. See ARCHITECTURE.md §3 for the full tenant data model.

Tenant-scoped behavior per request:

| Concern | Mechanism |
|---------|-----------|
| API credentials | Per-tenant Braiins key/secret, decrypted at request time |
| Settings cache | Redis key: `tenant:{id}:spot:settings` |
| Rate limits | Redis counter: `ratelimit:{id}:{tool}:{window}` |
| Spend caps | Per-tenant `max_order_usd` from tenant config |
| Audit log | Every tool call logged with `tenant_id` in PostgreSQL |
| Idempotency | Redis key: `idempotency:{id}:{client_order_id}`, 24h TTL |

### 3.2 Single-Tenant Mode (development)

Set `MCP_SINGLE_TENANT_MODE=true` and `SINGLE_TENANT_API_KEY=<key>` to bypass multi-tenant auth. This restores the single-process v0.1 behavior suitable for local development and direct Cursor/Claude Desktop integration.

---

## 4. Server Implementation

### Framework

The server is implemented using **FastMCP** from the `mcp` Python SDK:

```python
# braiins_hashpower_mcp/server.py
from mcp.server.fastmcp import FastMCP
from .middleware import TenantContextMiddleware

mcp = FastMCP("BraiinsHashpower")

# Tools, resources, and prompts are registered via decorators
# (see sections 5, 6, 7)

if __name__ == "__main__":
    mcp.run(transport="sse")
```

FastMCP handles:
- MCP protocol handshake and capability negotiation.
- Tool/resource/prompt registration and dispatch.
- SSE connection lifecycle management.

### Tenant Context Injection

Each request resolves tenant context before tool execution:

```python
# middleware.py
class TenantContext:
    tenant_id: str
    config: TenantConfig      # mode, dry_run_default, max_order_usd
    braiins_client: BraiinsClient  # pre-initialized with tenant credentials

# tools.py — tenant context accessed per-call
async def _get_tenant_context(request_headers: dict) -> TenantContext:
    tenant_id = request_headers.get("x-tenant-id")
    config = await tenant_config_loader.get(tenant_id)
    client = BraiinsClient(config.api_key, config.secret)
    return TenantContext(tenant_id=tenant_id, config=config, braiins_client=client)
```

---

## 5. Tools

Tools are **model-invoked actions**. The model calls them to retrieve data or perform mutations. All tools return a normalized response envelope.

### 5.1 Response Envelope

Every tool returns a JSON object matching:

```python
class MCPToolResponse(BaseModel):
    success: bool
    data: dict | list | None
    warnings: list[str] = []
    error: str | None = None
    request_id: str | None = None
    raw_api_status: int | None = None
    tenant_id: str | None = None  # included for audit transparency
```

### 5.2 Tool Definitions

---

#### `get_market_settings`

Fetch spot market configuration including price units, hashrate units, and market parameters.

**Must be called (or cache used) before any price or amount is submitted in an order.**

```python
@mcp.tool()
async def get_market_settings() -> MCPToolResponse:
    """
    Fetch current Braiins Hashpower spot market settings.
    Returns price unit (price_sat), hashrate unit (hr_unit), and
    min/max order bounds. Always call this before placing a bid to
    ensure correct unit interpretation.
    """
```

**Input schema:** none  
**Trust level:** Safe read  
**Caching:** Per-tenant Redis key with 60s TTL and distributed lock on refresh  
**Mapped endpoint:** `GET /spot/settings`  
**Metrics:** `mcp_tool_calls_total{tool="get_market_settings"}`

---

#### `get_orderbook`

Fetch current bid and ask depth for the spot market.

```python
@mcp.tool()
async def get_orderbook(
    market: Literal["spot"] = "spot",
    depth: int = 20
) -> MCPToolResponse:
    """
    Return bid/ask depth for the Braiins Hashpower spot market.
    Prices are in units from /spot/settings. Always call
    get_market_settings first to interpret values correctly.
    """
```

**Input schema:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `market` | `"spot"` | `"spot"` | Market identifier (only spot in v0.2) |
| `depth` | `int` | `20` | Number of levels to return per side |

**Trust level:** Safe read  
**Mapped endpoint:** `GET /spot/orderbook` or equivalent

---

#### `list_orders`

List user orders, optionally filtered by status.

```python
@mcp.tool()
async def list_orders(
    status: list[Literal["open", "filled", "canceled", "all"]] | None = None,
    limit: int = 50,
    cursor: str | None = None
) -> MCPToolResponse:
    """
    Return a paginated list of the authenticated tenant's orders.
    Defaults to all statuses if status is not specified.
    Use cursor for pagination.
    """
```

**Input schema:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | `list[str]` | `None` (all) | Filter by order status |
| `limit` | `int` | `50` | Max results per page |
| `cursor` | `str` | `None` | Pagination cursor from previous response |

**Trust level:** Safe read  
**Mapped endpoint:** `GET /spot/orders`

---

#### `get_account_summary`

Return balance, exposure, and account-level metadata.

```python
@mcp.tool()
async def get_account_summary() -> MCPToolResponse:
    """
    Return the authenticated tenant's current balance, open order
    exposure, and account-level metadata from Braiins Hashpower.
    """
```

**Input schema:** none  
**Trust level:** Safe read  
**Mapped endpoint:** `GET /account` or `/account/summary`

---

#### `get_deliveries`

Return hashrate delivery and allocation state post-trade.

```python
@mcp.tool()
async def get_deliveries(
    limit: int = 20,
    cursor: str | None = None
) -> MCPToolResponse:
    """
    Return hashrate delivery records and allocation state for
    filled orders. Useful for verifying that purchased hashrate
    has been allocated and is delivering as expected.
    """
```

**Input schema:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | `int` | `20` | Max results per page |
| `cursor` | `str` | `None` | Pagination cursor |

**Trust level:** Safe read  
**Mapped endpoint:** `GET /deliveries` or equivalent

---

#### `create_bid`

Place a spot-market bid. **Defaults to `dry_run=true`.**

```python
@mcp.tool()
async def create_bid(
    amount: float,
    price: float,
    market: Literal["spot"] = "spot",
    client_order_id: str | None = None,
    dry_run: bool = True
) -> MCPToolResponse:
    """
    Place a bid on the Braiins Hashpower spot market.

    IMPORTANT: Price and amount units are determined by /spot/settings.
    Always call get_market_settings first to verify units before
    composing inputs.

    dry_run=true (default) validates and returns a preview without
    submitting to the API. Set dry_run=false to place a live order.
    Requires tenant mode=trading. Blocked in read_only mode.
    """
```

**Input schema:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `amount` | `float` | required | Bid size in `hr_unit` from settings |
| `price` | `float` | required | Bid price in `price_sat` from settings |
| `market` | `"spot"` | `"spot"` | Market identifier |
| `client_order_id` | `str` | auto-generated UUID | Idempotency key — checked against Redis before submit |
| `dry_run` | `bool` | `true` (or tenant config default) | Preview without submitting if true |

**Trust level:** Sensitive write (requires tenant `mode=trading`)  
**Pre-flight validation flow:**

```
create_bid called
     │
     ▼
tenant.mode == "read_only"?  ─── YES ──► Return error: "Tenant in read_only mode"
     │ NO
     ▼
Check idempotency: Redis GET idempotency:{tenant_id}:{client_order_id}
   └── EXISTS ──► Return cached result (no duplicate submission)
     │
     ▼
Fetch /spot/settings (per-tenant Redis cache)
     │
     ▼
Validate amount within [min_amount, max_amount] from settings
     │
     ▼
Validate price > 0 and within sanity bounds
     │
     ▼
Validate notional <= tenant.max_order_usd
     │
     ▼
dry_run == true?  ─── YES ──► Return preview (no API call, no Redis write)
     │ NO
     ▼
POST /spot/bid → Braiins API
     │
     ▼
Store result in Redis idempotency:{tenant_id}:{client_order_id} (24h TTL)
     │
     ▼
Write to PostgreSQL orders table
     │
     ▼
Emit mcp_orders_placed_total metric
     │
     ▼
Return MCPToolResponse
```

**Mapped endpoint:** `POST /spot/bid`

---

#### `cancel_order`

Cancel an existing order by ID.

```python
@mcp.tool()
async def cancel_order(
    order_id: str
) -> MCPToolResponse:
    """
    Cancel an open order on the Braiins Hashpower spot market by
    its order ID. Use list_orders to retrieve valid order IDs.
    Requires tenant mode=trading. Blocked in read_only mode.
    """
```

**Input schema:**
| Field | Type | Description |
|-------|------|-------------|
| `order_id` | `str` | The order ID to cancel |

**Trust level:** Sensitive write (requires tenant `mode=trading`)  
**Mapped endpoint:** `DELETE /spot/orders/{order_id}` or equivalent

---

## 6. Resources

Resources are **application-exposed context** that clients and models can read. They use URI addressing and are suitable for caching, pre-loading context, and providing stable reference data.

Resources are scoped to the authenticated tenant. The URI scheme uses a `{tenant_id}` path prefix in the server-side resolution layer, even though clients address them by the logical URI.

### Resource Definitions

| URI | MIME Type | TTL | Description |
|-----|-----------|-----|-------------|
| `braiins://spot/settings` | `application/json` | 60s | Spot market settings and unit metadata |
| `braiins://account/orders/open` | `application/json` | 10s | Snapshot of tenant's open orders |
| `braiins://account/orders/history` | `application/json` | 60s | Last 50 filled/canceled orders |
| `braiins://account/summary` | `application/json` | 30s | Account balance and exposure |
| `braiins://docs/error-codes` | `application/json` | static | Normalized Braiins API error catalog |

```python
@mcp.resource("braiins://spot/settings")
async def resource_spot_settings() -> str:
    """Current Braiins Hashpower spot market settings including
    price units (price_sat) and hashrate units (hr_unit)."""
    # tenant_id resolved from request context
    settings = await settings_cache.get(tenant_id)
    return settings.model_dump_json()
```

---

## 7. Prompts

Prompts are **reusable user-invoked workflows** that guide the agent through multi-step tasks. They do not call tools directly but compose instructions that lead the agent to call the right tools in sequence.

### Prompt Definitions

---

#### `place-conservative-bid`

```python
@mcp.prompt()
def prompt_conservative_bid() -> str:
    """Guided workflow for placing a conservative spot bid."""
    return """
    You are helping a user place a conservative bid on Braiins Hashpower.

    Follow these steps in order:
    1. Call `get_market_settings` and explain the price and hashrate units to the user.
    2. Call `get_orderbook` with depth=10 and show the top 5 levels.
    3. Suggest a bid price that is 1-2% below the current best ask.
    4. Call `create_bid` with dry_run=true using the suggested values.
    5. Present the preview to the user and ask for explicit confirmation.
    6. Only call `create_bid` with dry_run=false after the user confirms.
    """
```

---

#### `review-open-orders`

```python
@mcp.prompt()
def prompt_review_open_orders() -> str:
    """Summarize open order exposure and recommend actions without mutating state."""
    return """
    Review the user's current open orders on Braiins Hashpower.

    Steps:
    1. Call `get_market_settings` to get current unit context.
    2. Call `list_orders` with status=["open"].
    3. Call `get_orderbook` to compare open bid prices against current market.
    4. Summarize: number of open bids, total exposure, distance from best ask.
    5. Recommend actions (e.g., cancel stale bids, adjust prices) but do NOT
       execute any changes without explicit user instruction.
    """
```

---

#### `explain-price-units`

```python
@mcp.prompt()
def prompt_explain_units() -> str:
    """Explain Braiins Hashpower spot-market units and pricing semantics."""
    return """
    Explain the Braiins Hashpower spot market pricing model to the user.

    Steps:
    1. Call `get_market_settings`.
    2. Explain what `price_sat` means: the price in satoshis per unit of hashrate.
    3. Explain what `hr_unit` means: the hashrate unit (e.g., TH/s) for the bid amount.
    4. Show an example: "A bid of X hr_units at Y price_sat/hr_unit costs Z BTC."
    5. Note that these units come directly from /spot/settings and may change.
    """
```

---

## 8. Configuration Reference

### Per-Deployment (environment / Kubernetes secrets)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `REDIS_URL` | Yes | — | Redis connection string (cluster or single) |
| `KMS_KEY_ID` | Yes (prod) | — | KMS key ID for credential decryption |
| `MCP_SERVER_HOST` | No | `0.0.0.0` | SSE server bind host |
| `MCP_SERVER_PORT` | No | `8765` | SSE server port |
| `MAX_CONNECTIONS_PER_NODE` | No | `500` | Max concurrent SSE connections per pod |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | OpenTelemetry collector endpoint |

### Single-Tenant / Development Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SINGLE_TENANT_MODE` | `false` | Bypass multi-tenant auth |
| `SINGLE_TENANT_API_KEY` | — | Static API key for dev mode |
| `BRAIINS_API_BASE_URL` | `https://hashpower.braiins.com/api` | API base URL |
| `BRAIINS_API_KEY` | — | Direct Braiins API key (single-tenant only) |
| `BRAIINS_API_SECRET` | — | Direct Braiins API secret (single-tenant only) |
| `BRAIINS_MODE` | `read_only` | `read_only` or `trading` |
| `BRAIINS_DRY_RUN_DEFAULT` | `true` | Default dry_run value for create_bid |
| `BRAIINS_MAX_ORDER_USD` | `500` | Max notional per order in USD |

### Per-Tenant (PostgreSQL `tenants` table)

| Column | Description |
|--------|-------------|
| `braiins_api_key` | Encrypted Braiins API key |
| `braiins_secret` | Encrypted Braiins API secret |
| `mode` | `read_only` or `trading` |
| `dry_run_default` | Default dry_run value for this tenant |
| `max_order_usd` | Per-tenant spend cap |
| `rate_limit_rpm` | Requests per minute limit |

---

## 9. Safety Model

### 9.1 Trust Tiers

| Tier | Tools | Gate |
|------|-------|------|
| Safe read | `get_market_settings`, `get_orderbook`, `list_orders`, `get_account_summary`, `get_deliveries` | No gate |
| Sensitive write | `create_bid`, `cancel_order` | `tenant.mode=trading` + `dry_run` default |
| Future: High-risk | Bulk cancel, ladder placement | Explicit `allow_bulk=true` tenant flag (v0.3) |

### 9.2 Multi-Layer Safety Stack

```
Agent request
    │
    ▼
[Layer 1] API Gateway: Bearer token auth, global rate limit
    │
    ▼
[Layer 2] MCP Node: tenant.mode check (read_only blocks writes)
    │
    ▼
[Layer 3] Idempotency: client_order_id Redis check (deduplication)
    │
    ▼
[Layer 4] Settings validation: amount/price vs. /spot/settings bounds
    │
    ▼
[Layer 5] Spend cap: notional <= tenant.max_order_usd
    │
    ▼
[Layer 6] dry_run gate: preview mode by default, explicit false required
    │
    ▼
Braiins API call
```

---

## 10. Error Handling

All Braiins API errors are mapped to structured MCP tool errors via `errors.py`:

```python
BRAIINS_ERROR_MAP = {
    400: "INVALID_REQUEST",
    401: "AUTHENTICATION_FAILED",
    403: "FORBIDDEN",
    404: "ORDER_NOT_FOUND",
    409: "ORDER_CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "BRAIINS_INTERNAL_ERROR",
}
```

All tools return `success=False` with a human-readable `error` string and `raw_api_status`. Auth errors from the tenant credential layer use `AUTHENTICATION_FAILED` and are indistinguishable from Braiins-level auth errors (no tenant info is leaked in error messages).

### Circuit Breaker (Braiins API)

```python
# client.py — using tenacity
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=0.5, max=4),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
async def _call_braiins_api(self, method, path, **kwargs):
    ...
```

After 10 consecutive 5xx responses from Braiins, a circuit breaker opens and all calls fail fast with `BRAIINS_UNAVAILABLE` for 30 seconds before a half-open probe.

---

## 11. Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastMCP instantiation, SSE transport startup, health/ready endpoints |
| `middleware.py` | Tenant context resolution from `X-Tenant-Id` header |
| `mcp/tools.py` | `@mcp.tool()` definitions; input parsing; delegate to braiins/ and safety/ |
| `mcp/resources.py` | `@mcp.resource()` definitions; TTL caching; tenant-scoped serialization |
| `mcp/prompts.py` | `@mcp.prompt()` definitions; static prompt strings |
| `mcp/schemas.py` | Pydantic models for all tool inputs and `MCPToolResponse` |
| `braiins/client.py` | Async httpx client; circuit breaker; retry via tenacity |
| `braiins/auth.py` | HMAC/API key request signing; credential decryption via KMS |
| `braiins/settings_cache.py` | Per-tenant Redis cache for `/spot/settings` with distributed lock |
| `braiins/orders.py` | `list_orders`, `create_bid`, `cancel_order` API calls |
| `braiins/market.py` | `get_orderbook`, `get_deliveries` API calls |
| `braiins/errors.py` | HTTP status → structured MCP error mapping; circuit breaker |
| `tenants/loader.py` | Tenant config loader with Redis cache and PostgreSQL fallback |
| `tenants/models.py` | `TenantConfig`, `TenantContext` Pydantic models |
| `safety/approvals.py` | Tenant mode check; write-action gate |
| `safety/limits.py` | Per-tenant `max_order_usd` enforcement |
| `safety/validators.py` | Unit normalization against settings; pre-flight checks |
| `safety/idempotency.py` | Redis idempotency key check and store |
| `infra/redis.py` | Redis connection pool; distributed lock helpers |
| `infra/postgres.py` | Async PostgreSQL pool (asyncpg) |
| `infra/metrics.py` | Prometheus counters, histograms, gauges |
| `infra/tracing.py` | OpenTelemetry tracer setup and span helpers |
| `infra/logging.py` | structlog configuration; structured JSON output |

---

## 12. Dependencies

```toml
[project]
name = "braiins-hashpower-mcp"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "mcp[server]>=1.9.1",
    "httpx>=0.27.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.7.0",
    "tenacity>=8.3.0",
    "python-dotenv>=1.0.0",
    "redis[hiredis]>=5.0.0",
    "asyncpg>=0.29.0",
    "structlog>=24.0.0",
    "prometheus-client>=0.20.0",
    "opentelemetry-sdk>=1.24.0",
    "opentelemetry-exporter-otlp>=1.24.0",
    "cryptography>=42.0.0",
    "bcrypt>=4.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.4",
    "mypy>=1.10",
    "langchain-mcp-adapters>=0.1.0",
    "fakeredis>=2.23",
    "pytest-postgresql>=6.0",
]
```

---

## 13. Testing Strategy

| Test Layer | Tool | Coverage |
|------------|------|---------|
| Unit: tool logic | pytest + respx | All 7 tools; success and error paths |
| Unit: safety validators | pytest | Boundary checks, mode gate, spend cap |
| Unit: settings cache | pytest + fakeredis | TTL expiry, distributed lock, refresh |
| Unit: idempotency | pytest + fakeredis | Dedup on second call, 24h TTL |
| Unit: tenant loader | pytest + fakeredis + pytest-postgresql | Config cache hit/miss |
| Integration: SSE transport | pytest-asyncio + langchain-mcp-adapters | Full round-trip via `MultiServerMCPClient` |
| Integration: multi-tenant | pytest-asyncio | Two tenants, isolated settings caches and creds |
| Integration: dry_run | pytest-asyncio | `create_bid` with dry_run=true never hits Braiins API |
| Load: SSE connections | locust | 500 concurrent SSE connections per node |

---

## 14. Versioning and Roadmap

### v0.1 (initial spec)
- Single-tenant SSE transport
- 7 tools (5 safe read, 2 sensitive write)
- 5 resources
- 3 prompts
- `dry_run` default, `read_only` mode, spend cap

### v0.2 (this spec)
- Multi-tenant support with per-tenant credential isolation
- Stateless nodes with Redis shared state
- PostgreSQL audit log and order mirror
- API gateway + auth service integration
- Idempotency via Redis
- Prometheus metrics, structlog, OpenTelemetry tracing
- Circuit breaker for Braiins API
- Health/ready endpoints for Kubernetes
- `streamable_http` as secondary transport option
- Docker Compose dev stack

### v0.3 (planned)
- Hashrate DCA / ladder placement prompt
- Portfolio exposure resource
- ClickHouse integration for analytics-scale audit queries
- Multi-account / sub-account support
- Human-in-the-loop approval flow for live orders
- Bulk cancel tool (high-risk tier, explicit opt-in)

---

## References

- [Braiins Hashpower API Reference](https://hashpower.braiins.com/api/)
- [Braiins Academy: Public API](https://academy.braiins.com/en/braiins-hashpower/api/)
- [langchain-mcp-adapters GitHub](https://github.com/langchain-ai/langchain-mcp-adapters)
- [FastMCP / mcp SDK](https://github.com/jlowin/fastmcp)
- [Model Context Protocol — Server Concepts](https://modelcontextprotocol.io/docs/learn/server-concepts)
- [LangGraph Prebuilt Agents](https://langchain-ai.github.io/langgraph/reference/prebuilt/)
- ARCHITECTURE.md (this repository)
