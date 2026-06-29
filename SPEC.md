# SPEC.md — Braiins Hashpower MCP Server

**Version:** 1.0.0-ths  
**Status:** Draft aligned to THS-PRD-MCP-001  
**Owner:** Platform Engineering  
**Last Updated:** 2026-06-29  
**Transport:** SSE (primary) + Streamable HTTP (planned)  
**Scope:** Braiins Hashpower spot-market operations, order management, and safe agent workflows  

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Data Domain Model](#2-data-domain-model)
3. [External Integrations](#3-external-integrations)
4. [MCP Interface Design](#4-mcp-interface-design)
5. [Analytics and Reasoning Layer](#5-analytics-and-reasoning-layer)
6. [Performance Architecture](#6-performance-architecture)
7. [Reliability and Operations](#7-reliability-and-operations)
8. [Security and Trust Boundaries](#8-security-and-trust-boundaries)
9. [Data Quality and Semantics](#9-data-quality-and-semantics)
10. [Developer Experience](#10-developer-experience)
11. [Recommended Implementation Stack](#11-recommended-implementation-stack)
12. [Example User Queries](#12-example-user-queries)
13. [Roadmap](#13-roadmap)
   - [13.4 A2A and Deployment Rollout](#134-a2a-and-deployment-rollout)

---

## 1. Product Overview

### 1.1 Problem Statement

Braiins Hashpower operations require safe, structured, machine-readable control surfaces for market data, open orders, execution previews, and live order mutation. Human operators and autonomous agents currently have to reason across upstream Braiins endpoints, cached market settings, order state, and safety rules. This MCP server turns those interactions into deterministic tool calls with explicit validation, auditability, and deployment discipline.

This server is the policy and orchestration layer for Braiins Hashpower spot-market workflows. It is designed for current order-management use cases and is structured so it can later expand toward broader Braiins OS+ hashpower/autotuning workflows without changing the core safety model.

### 1.2 Target Users

| User Class | Description |
|---|---|
| Mining operators | Need safe bid placement, cancellation, and market state inspection |
| Autonomous agents | Need deterministic tool calls, structured outputs, and bounded side effects |
| SRE / infrastructure teams | Need auditable operations, metrics, and predictable deployment behavior |
| Analysts | Need normalized market context for reasoning about price units and order exposure |
| Platform integrators | Need MCP-compatible tools/resources/prompts for LangGraph, Claude, Cursor, and similar clients |

### 1.3 Primary Goals

- Provide a safe MCP interface for Braiins Hashpower market operations.
- Default all mutating workflows to preview/dry-run mode.
- Enforce server-side validation against `/spot/settings` before live order submission.
- Preserve tenant isolation, request traceability, and auditability.
- Support horizontally scalable, stateless runtime nodes.
- Expose schema-stable tools, resources, and prompts for AI clients.

### 1.4 Non-Goals

- Futures or non-spot market products.
- Withdrawal, treasury, or wallet-custody workflows.
- Unbounded free-form execution without policy gates.
- Narrative report generation or chart rendering.
- Direct upstream API exposure to clients outside MCP.

### 1.5 Success Criteria

- 100% of mutating tool calls are validated, audited, and idempotent.
- 100% of tool definitions include `x-ths-metadata`.
- Read-only tool calls can be served from cache with deterministic freshness rules.
- Live writes are blocked when mode, scope, or hitl policy disallows them.
- Production deploys are repeatable via Ansible and observable via Prometheus/Otel.

---

## 2. Data Domain Model

### 2.1 Core Entities

#### Spot Market Settings
Canonical unit and market metadata returned by Braiins `/spot/settings`.

Key fields:
- `price_sat` — price denomination
- `hr_unit` — hashrate unit denomination
- min/max order bounds
- market identifiers and policy flags

#### Orderbook Snapshot
Bid/ask depth used for price discovery and conservative bid placement.

#### Active Order
A live, tenant-scoped order that can be listed, previewed, or canceled.

#### Order History
Closed, filled, or canceled orders used for review and reconciliation.

#### Account Summary
Balance/exposure summary used for operator context and risk review.

#### Delivery / Allocation State
Post-fill state that indicates whether purchased hashrate is delivering as expected.

### 2.2 Canonical Semantics

| Concept | Canonical Form | Notes |
|---|---|---|
| Time | RFC 3339 UTC | Always emit `Z`-suffixed timestamps |
| Price | `price_sat` | Integer satoshi representation, no floating-point writes |
| Amount | `amount_sat` or upstream unit from settings | Always normalized against current market settings |
| Idempotency | `client_order_id` | Canonical idempotency key for writes |
| Dry run | `dry_run: true` | Default for all mutating tools |
| Tenant scope | Request-bound | Never inferred from client payload |

### 2.3 Derived State

| Derived Entity | Description |
|---|---|
| Conservative bid preview | Safe draft output computed before live submission |
| Exposure summary | Aggregated open-order notional and order count |
| Staleness indicator | Cache freshness and upstream health signal |
| Execution eligibility | Whether the current request may mutate state |

---

## 3. External Integrations

### 3.1 Braiins Hashpower API

Primary upstream dependency: the Braiins Hashpower REST API.

**Canonical base URL:** `https://hashpower.braiins.com/api`  
**Auth:** Braiins API key / secret managed server-side  
**Transport:** HTTPS only

Known upstream surfaces used by this server:

| Endpoint | Use |
|---|---|
| `GET /spot/settings` | Market units, bounds, and normalization inputs |
| `GET /spot/orderbook` | Market depth and best bid/ask |
| `GET /spot/orders` | Full order listing |
| `GET /spot/orders/active` | Open orders / active exposure |
| `POST /spot/bid` | Create bid |
| `DELETE /spot/orders/{order_id}` | Cancel order |

### 3.2 API Key Handling

- Credentials never leave the server process.
- Credentials are never returned in tool output or logged in plaintext.
- Single-tenant development may use `BRAIINS_API_KEY` / `BRAIINS_API_SECRET`.
- Multi-tenant deployments must resolve tenant credentials from a secrets manager.
- Request contexts must not pass upstream secrets to MCP clients.

### 3.3 Rate Limits and Retry Policy

Default upstream policy:
- 60 outbound requests/minute soft ceiling
- Exponential backoff with jitter on 429/5xx
- Circuit breaker after repeated upstream failures
- Prefer cached results for read-only requests when available

### 3.4 Tier-Gated Data and Degradation

The server must support tier-aware behavior for upstream data or future premium features.

| Tier State | Behavior |
|---|---|
| Tier available | Return full payload |
| Tier insufficient | Return `THS_ERR_TIER_INSUFFICIENT` or a structured downgrade response |
| Upstream unavailable | Serve stale cache if within policy window |
| Stale beyond threshold | Fail closed with structured error |

### 3.5 Internal Supporting Integrations

| Integration | Purpose |
|---|---|
| Redis | L1/L2 cache, idempotency, lock coordination |
| PostgreSQL | Audit log, request history, operational traces |
| Prometheus | Metrics collection and alerting |
| OpenTelemetry | Trace propagation and span correlation |
| Ansible | Deployment, lifecycle, discovery registration |

---

## 4. MCP Interface Design

### 4.1 Transport and Protocol Behavior

- Primary transport: SSE.
- Secondary transport: streamable HTTP when enabled.
- MCP tools, resources, and prompts must remain schema-stable.
- All tool calls must include request correlation identifiers.
- All mutating requests must honor dry-run and approval gates.

### 4.2 Current Tool Set

| Tool | Type | Description |
|---|---|---|
| `get_market_settings` | Read | Fetch current spot settings and unit metadata |
| `get_orderbook` | Read | Fetch orderbook depth |
| `list_orders` | Read | List orders with optional status filtering |
| `get_deliveries` | Read | Return delivery/allocation state |
| `create_bid` | Write | Place a bid, defaulting to dry-run |
| `cancel_order` | Write | Cancel an existing order, defaulting to dry-run |

### 4.3 Required `x-ths-metadata`

Every tool definition MUST include `x-ths-metadata` with at minimum the following fields.

| Field | Type | Meaning |
|---|---|---|
| `zone` | enum | Security zone such as `Z0`, `Z1`, `Z2`, `Z3` |
| `is_mutating` | boolean | Whether the tool changes external state |
| `requires_hitl` | boolean | Whether human approval is required |
| `risk_level` | enum | `low`, `medium`, `high`, `critical` |
| `scopes_required` | string[] | OAuth / policy scopes required |
| `permitted_agent_roles` | string[] | Roles allowed to invoke the tool |
| `tool_schema_version` | semver | Independent schema version for the tool contract |

Recommended additional fields:
- `server`
- `category`
- `cooldown_seconds`
- `audit_required`
- `deprecated`
- `experimental`

### 4.4 Tool Metadata Matrix

| Tool | zone | is_mutating | requires_hitl | risk_level | scopes_required | permitted_agent_roles | tool_schema_version |
|---|---:|---:|---:|---|---|---|---|
| `get_market_settings` | Z1 | false | false | low | `ths:market:read` | `market-reader`, `sre-read-only`, `operator` | 1.0.0 |
| `get_orderbook` | Z1 | false | false | low | `ths:market:read` | `market-reader`, `operator` | 1.0.0 |
| `list_orders` | Z1 | false | false | medium | `ths:market:read` | `market-reader`, `operator`, `sre-read-only` | 1.0.0 |
| `get_deliveries` | Z1 | false | false | medium | `ths:market:read` | `market-reader`, `operator` | 1.0.0 |
| `create_bid` | Z0 | true | true | critical | `ths:market:write` | `trader`, `performance-tuner`, `operator` | 1.0.0 |
| `cancel_order` | Z0 | true | true | critical | `ths:market:write` | `trader`, `operator` | 1.0.0 |

### 4.5 THS Error Envelope Format

All errors must use a structured envelope with `THS_ERR_*` codes.

**Required fields:**
- `ok`: `false`
- `error_code`: `THS_ERR_*`
- `message`: human-readable summary
- `http_status`: HTTP status code
- `request_id`: correlation identifier
- `retryable`: boolean
- `details`: optional object

**Example:**

```json
{
  "ok": false,
  "error_code": "THS_ERR_AUTH_INVALID",
  "message": "Invalid or expired Braiins credential.",
  "http_status": 401,
  "request_id": "ab12cd34",
  "retryable": false,
  "details": {
    "tool": "create_bid",
    "zone": "Z0"
  }
}
```

Common categories:
- `THS_ERR_AUTH_*`
- `THS_ERR_SCOPE_*`
- `THS_ERR_VALIDATION_*`
- `THS_ERR_TIER_*`
- `THS_ERR_CACHE_*`
- `THS_ERR_UPSTREAM_*`
- `THS_ERR_APPROVAL_*`

### 4.6 Resource Inventory

| Resource URI | MIME Type | Description |
|---|---|---|
| `braiins://spot/settings` | `application/json` | Current market settings and units |
| `braiins://account/orders/open` | `application/json` | Open orders snapshot |
| `braiins://account/orders/history` | `application/json` | Order history snapshot |
| `braiins://account/summary` | `application/json` | Account summary / exposure |
| `braiins://docs/error-codes` | `application/json` | Structured error catalog |

### 4.7 Prompt Inventory

| Prompt | Intent |
|---|---|
| `place_conservative_bid` | Assist with low-risk bid placement |
| `review_open_orders` | Summarize existing exposure and recommend actions |
| `explain_price_units` | Explain unit semantics and pricing interpretation |

### 4.8 Tool Safety Behavior

- `create_bid` defaults to `dry_run=true`.
- `cancel_order` defaults to `dry_run=true`.
- `list_orders` accepts status filtering and pagination.
- `get_market_settings` must be treated as a prerequisite for any price-sensitive workflow.
- All write tools must enforce idempotency via `client_order_id`.

---

## 5. Analytics and Reasoning Layer

### 5.1 Reasoning Responsibilities

The server should help agents reason about Braiins market actions, not just relay API responses.

Key reasoning functions:
- Normalize units from live market settings.
- Compare bids against market depth.
- Produce conservative previews before live writes.
- Detect stale or duplicate write requests.
- Classify whether an action is safe, sensitive, or blocked.

### 5.2 Deterministic Analysis Rules

- Never infer live price/amount units without `/spot/settings`.
- Never convert between units using floating-point writes.
- Never hide upstream uncertainty; annotate stale or partial data.
- Never convert a dry-run result into a live action without explicit confirmation.
- Treat `client_order_id` collisions as idempotent replays, not new actions.

### 5.3 Reasoning Workflows

| Workflow | Input | Output |
|---|---|---|
| Conservative bid planning | Settings + orderbook | Suggested bid preview |
| Open order review | Orders + depth | Exposure summary and stale-order hints |
| Live bid validation | Settings + request | Pass/fail with normalized amounts |
| Cancellation review | Order status + history | Cancellation preview and safety note |

### 5.4 Human-in-the-Loop Logic

HITL is required for live state changes, especially when:
- the tool is mutating,
- the requested action is in `Z0`,
- the request exceeds configured spend/risk thresholds,
- the agent role lacks explicit write permission,
- the context is degraded or ambiguous.

---

## 6. Performance Architecture

### 6.1 Cache Architecture

The server must use a two-tier cache:

- **L1:** in-process cache for hot, request-local reads
- **L2:** Redis for shared state across nodes

Recommended cache policy:
- `get_market_settings`: short TTL, strong invalidation
- `get_orderbook`: very short TTL, freshness preferred
- `list_orders`: short TTL, tenant-scoped
- `account summary`: short TTL, request-scoped if necessary

### 6.2 Cache Invalidation

- Any mutating tool invalidates related cache keys.
- Idempotency records must survive long enough to suppress duplicate writes.
- Cache stale-on-error behavior is allowed only for read paths and only within policy bounds.

### 6.3 Latency Targets

| Path | Target |
|---|---|
| Cached read | p99 < 200 ms |
| Uncached read | p99 < 500 ms |
| Dry-run write | p99 < 500 ms |
| Live write | p99 < 1 s under normal upstream conditions |

### 6.4 Concurrency and Backpressure

- Use bounded concurrency per pod.
- Prefer fail-fast behavior on upstream saturation.
- Protect the upstream with circuit breakers and retry budgets.
- Degrade to cached read behavior when upstream is unstable.

### 6.5 Observability Metrics

Required Prometheus metrics:
- `ths_mcp_tool_calls_total`
- `ths_mcp_tool_latency_seconds`
- `ths_mcp_auth_errors_total`
- `ths_mcp_cache_hits_total`
- `ths_mcp_cache_misses_total`
- `ths_mcp_upstream_circuit_breaker_state`
- `ths_mcp_sse_sessions_active`
- `ths_mcp_idempotency_replays_total`
- `ths_mcp_audit_events_total`

Label dimensions should include `tool`, `zone`, `agent_role`, `status`, and `cache_tier` where applicable.

---

## 7. Reliability and Operations

### 7.1 Operational Model

- Stateless application pods.
- Shared cache and audit systems.
- Readiness depends on upstream credentials, cache connectivity, and core config validation.
- Liveness checks should not depend on upstream availability.

### 7.2 Resilience Controls

- Timeouts on all upstream calls.
- Circuit breaker on Braiins API failures.
- Retry only on safe transient conditions.
- Graceful degradation to stale cached data for reads.
- Explicit failure for live writes when upstream or policy checks fail.

### 7.3 Audit and Logging

All tool invocations must produce structured JSON logs including:
- `request_id`
- `tool`
- `zone`
- `agent_role`
- `tenant_id` or equivalent request scope
- `status`
- `error_code` when applicable

### 7.4 Required Health Endpoints

| Endpoint | Purpose |
|---|---|
| `/healthz` | Liveness |
| `/readyz` | Readiness |
| `/metrics` | Prometheus scrape |
| `/.well-known/agent-card.json` | A2A discovery |
| `/.well-known/oauth-protected-resource` | OAuth protected resource metadata |

### 7.5 Ansible Deployment Reference

Every deployment MUST have an `ansible/` playbook structure at the repo root. The canonical structure should follow the THS deployment convention:

```text
ansible/
├── playbook.yml
├── inventory/
│   ├── production.yml
│   └── edge.yml
├── group_vars/
│   ├── all.yml
│   ├── datacenter.yml
│   └── edge.yml
├── host_vars/
├── roles/
│   ├── mcp_server/
│   ├── discovery/
│   ├── proxy/
│   ├── cache/
│   ├── observability/
│   ├── security/
│   └── maintenance/
└── templates/
    ├── agent-card.json.j2
    ├── oauth-protected-resource.json.j2
    ├── mcp-server-deployment.yaml.j2
    ├── redis-cluster.yaml.j2
    ├── cilium-network-policy.yaml.j2
    └── gateway-route.yaml.j2
```

Playbook responsibilities:
- deploy server images
- register discovery metadata
- configure caches and observability
- manage security artifacts
- support rollback and maintenance operations

---

## 8. Security and Trust Boundaries

### 8.1 Security Posture

This server is an OAuth 2.1 resource server, not a token issuer.

Core rules:
- Validate bearer tokens on every request.
- Enforce audience binding.
- Reject token passthrough to upstream APIs.
- Use mTLS for service-to-service communication.
- Keep secrets out of logs, env dumps, and response payloads.

### 8.2 Trust Boundaries

| Boundary | Control |
|---|---|
| Client → MCP server | OAuth / policy validation |
| MCP server → upstream API | Server-side credentials only |
| Pod → pod | mTLS + network policy |
| Tool → audit store | Append-only logging and trace correlation |
| Live write → external state | HITL / approval gate |

### 8.3 Security Gates

Before production rollout, verify:
- valid OAuth protected resource metadata
- audience validation
- scope enforcement per tool
- replay resistance
- secret delivery from approved secret store
- no raw secret material in app memory dumps or logs
- live write tools gated by role and HITL

### 8.4 Risk-Based Tool Policy

| Zone | Example Tools | Policy |
|---|---|---|
| Z1 | Read tools | No HITL, standard auth, cache allowed |
| Z0 | Live writes | HITL required, strict audit, idempotency required |

---

## 9. Data Quality and Semantics

### 9.1 Validation Rules

- All schemas must be strict with `additionalProperties: false`.
- Numeric inputs must have min/max constraints and unit annotations.
- Resource outputs must be deterministic and well-typed.
- Empty or partial upstream data must be explicitly marked.

### 9.2 Freshness Semantics

- Every cached response should carry a freshness indicator.
- Stale read responses must label the age of the data.
- Hard stale thresholds should fail closed for live-sensitive outputs.

### 9.3 Pagination and Determinism

- Pagination must be explicit and stable.
- Order listings should preserve deterministic sort behavior where possible.
- Replayed write requests should produce the same result envelope.

### 9.4 Error Semantics

- Validation, tier, auth, approval, cache, and upstream failures must be distinct.
- Errors should be concise, structured, and actionable.
- Error payloads must not leak secrets or internal implementation details.

---

## 10. Developer Experience

### 10.1 Local Development Workflow

Recommended workflow:
- install dependencies
- run the MCP server locally
- connect via MCP Inspector or an MCP-compatible client
- use fixtures/mock upstream data for deterministic testing
- run unit, integration, lint, type, and security checks before merge

### 10.2 Environment Variables

| Variable | Purpose |
|---|---|
| `BRAIINS_API_KEY` | Braiins API key |
| `BRAIINS_API_SECRET` | Braiins API secret |
| `BRAIINS_API_BASE_URL` | Upstream API base URL |
| `BRAIINS_MODE` | `read_only` or `trading` |
| `BRAIINS_DRY_RUN_DEFAULT` | Default dry-run behavior |
| `MCP_SERVER_HOST` | Bind host |
| `MCP_SERVER_PORT` | Listen port |
| `REDIS_URL` | Shared cache / idempotency store |
| `DATABASE_URL` | Audit log database |
| `LOG_LEVEL` | Logging verbosity |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Trace export endpoint |
| `MCP_SINGLE_TENANT_MODE` | Development bypass for multi-tenant auth |
| `SINGLE_TENANT_API_KEY` | Development API key |

### 10.3 Developer Tooling

- `Makefile` targets for install, test, lint, format, typecheck, and run.
- `pytest` for unit and integration tests.
- `ruff` and `mypy` for code quality.
- MCP Inspector or equivalent for manual protocol checks.
- Fixture-based offline testing for predictable developer loops.

### 10.4 API and Prompt Authoring Guidance

- Keep tool names stable and descriptive.
- Prefer explicit over implicit inputs.
- Encode safety expectations in schema and metadata, not just prompts.
- Ensure prompts route to bounded tools only.
- Document every tool/resource with examples.

---

## 11. Recommended Implementation Stack

| Layer | Recommendation |
|---|---|
| Language | Python 3.13 |
| Package manager | `uv` |
| MCP framework | FastMCP / `mcp` SDK |
| Validation | Pydantic v2 |
| HTTP client | `httpx` |
| Cache | Redis + in-process LRU |
| Logging | `structlog` |
| Metrics | `prometheus-client` |
| Tracing | OpenTelemetry SDK |
| Persistence | PostgreSQL for audit/logging |
| Deployment | Docker + Kubernetes + Ansible |
| Secret management | Bitwarden ESC / equivalent secrets provider |
| Security | OAuth 2.1, mTLS, Cilium NetworkPolicy |

---

## 12. Example User Queries

1. “Show me the current Braiins spot settings and explain the price unit.”
2. “Give me the current orderbook and suggest a conservative bid.”
3. “List my open orders and tell me which ones are stale.”
4. “Prepare a dry-run cancel for order `B123`.”
5. “Create a live bid only if the preview is within my operator policy.”
6. “Review recent orders and summarize current exposure.”

---

## 13. Roadmap

### 13.1 Phase 0 — Contract Lock and Spec Alignment

Deliverables:
- Final tool/resource/prompt inventory
- Strict JSON schemas and metadata contract
- THS error envelope normalization
- Security zone assignment per tool

Exit criteria:
- All tools have `x-ths-metadata`
- Tool contracts are stable and documented
- Error semantics are consistent across handlers

### 13.2 Phase 1 — Core MCP Server Hardening

Deliverables:
- SSE transport stabilized
- Read tools fully implemented and cached
- Write tools gated by dry-run and idempotency
- Structured audit logging and baseline metrics

Exit criteria:
- Read/write workflows pass integration tests
- No secret leakage in logs or responses
- Resource and prompt surfaces are validated

### 13.3 Phase 2 — Operational Maturity

Deliverables:
- Two-tier caching
- Prometheus / OTel observability
- Circuit breaker and retry budgets
- CI quality gates and security scans
- Deployment readiness checks

Exit criteria:
- p99 latency targets met for cached reads
- Alerting rules and dashboards are live
- Security gates pass in CI and pre-prod

### 13.4 A2A and Deployment Rollout

Deliverables:
- Schema-valid `agent-card.json` at `/.well-known/agent-card.json`
- A2A route and policy registration
- Named prompt playbook references for delegated tasks
- Ansible deployment playbook in repository root
- Discovery registration and rollback workflow

Rollout sequence:
1. Validate Agent Card schema.
2. Register the agent in discovery services.
3. Deploy via Ansible to staging.
4. Run smoke and contract tests.
5. Promote to production with observability gates.
6. Verify health, metrics, and audit trails after rollout.

---

### Appendix E.1: Braiins Hashpower — A2A Agent Card Specification

Every deployment of this server MUST expose a schema-valid Agent Card at `/.well-known/agent-card.json`.

| Field | Value / Requirement | Notes |
|---|---|---|
| `agent_id` | `ths-braiins-hashpower` | Stable registry identifier |
| `display_name` | Braiins Hashpower Market Agent | Human-readable name |
| `version` | Semver | Independent of runtime package version |
| `domain` | `market` | Functional domain |
| `framework` | `mcp` | Runtime label |
| `llm_profile` | Model/router profile | Deterministic, low-temperature recommendation |
| `memory_profile` | Backend and retention | Prefer ephemeral or policy-limited memory |
| `specialized_skills` | Bounded skill labels | Examples: `market-data-read`, `order-review`, `safe-execution` |
| `mcp_tool_map` | Skill-to-tool mapping | Maps skills to allowed MCP tools and scopes |
| `resource_uris` | Read-only/controlled resources | Include `braiins://spot/settings`, open orders, history |
| `safety_requirements` | Safety bounds | Must include dry-run and confirmation expectations |
| `confirmation_workflows` | Approval gates | Required for live writes |
| `auth_profiles` | Local and cloud auth patterns | mTLS / OAuth / equivalent |
| `prompt_playbooks` | Named workflows | Examples: conservative bid, review orders, explain units |
| `usage_patterns` | Discovery hints | Canonical task descriptions |
| `a2a_callable` | `true` / `false` | Whether peer agents may delegate to this agent |
| `customer_visible` | Boolean | Usually internal-only |
| `owner_team` | Team name | Responsible operational owner |
| `deployment_target` | Platform target | Kubernetes, VM, or edge target |
| `risk_level` | `low` / `medium` / `high` / `critical` | Overall agent risk profile |
| `hitl_policy` | Human approval policy summary | Required approval behavior |

Minimum schema constraints:
- JSON Schema 2020-12
- `additionalProperties: false`
- versioned independently of server package
- published with a stable URL and audit-visible change history

---

### Appendix E.2: Deployment Playbook Structure Reference

The canonical Ansible layout should follow this pattern:

```text
ansible/
├── playbook.yml
├── inventory/
│   ├── production.yml
│   └── edge.yml
├── group_vars/
│   ├── all.yml
│   ├── datacenter.yml
│   └── edge.yml
├── host_vars/
├── roles/
│   ├── mcp_server/
│   ├── discovery/
│   ├── proxy/
│   ├── cache/
│   ├── observability/
│   ├── security/
│   └── maintenance/
└── templates/
    ├── agent-card.json.j2
    ├── oauth-protected-resource.json.j2
    ├── mcp-server-deployment.yaml.j2
    ├── redis-cluster.yaml.j2
    ├── cilium-network-policy.yaml.j2
    └── gateway-route.yaml.j2
```

This reference is included so the repo can be brought into THS deployment compliance without redefining deployment conventions in ad hoc scripts.
