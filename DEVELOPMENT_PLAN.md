# Braiins Hashpower MCP Server — Development Plan

**Status:** THS alignment plan  
**Last updated:** 2026-06-29  
**Primary source:** `SPEC.md`  
**Repository:** `/home/elvis/projects/RynoCrypto/braiins-hashpower-mcp-server`  

---

## 1. Project Goal

Build and operate a THS-compliant MCP server for Braiins Hashpower market operations with strict schema contracts, tier-aware behavior, deterministic safety gates, structured errors, and production-grade deployment automation.

Current baseline in the repository:
- SSE-based MCP server
- 6 core tools plus resources and prompts
- dry-run-first write path
- basic safety gates and structured responses
- local development support

This plan formalizes the remaining work needed to align the server with THS-PRD-MCP-001.

---

## 2. Current Implementation Snapshot

Implemented today:
- `get_market_settings`
- `get_orderbook`
- `list_orders`
- `get_deliveries` stubbed as a controlled failure path
- `create_bid`
- `cancel_order`
- resources for spot settings, order lists, summary, and error codes
- prompts for conservative bid placement, order review, and unit explanation
- safety modules for approval, validation, spend limiting, and idempotency

Current gaps vs. THS standard:
- `x-ths-metadata` is not yet formalized on every tool
- THS error envelope (`THS_ERR_*`) needs explicit contract normalization
- Ansible deployment structure is not yet present in the repo
- A2A agent card and discovery rollout are not yet implemented
- observability and security gates need THS-specific documentation and coverage

---

## 3. Delivery Phases

### Phase 0 — Contract Lock and THS Normalization

**Objectives**
- Lock the canonical tool/resource/prompt inventory.
- Normalize error handling to the THS envelope.
- Add required metadata contract for every tool.
- Freeze scope, zones, roles, and gating behavior.

**Deliverables**
- Updated `SPEC.md` and supporting schema references
- `x-ths-metadata` contract for all tools
- `THS_ERR_*` error mapping and envelope examples
- Tool-to-zone / tool-to-role matrix
- Acceptance tests for schema and error normalization

**Quality gates**
- Every tool definition includes `zone`, `is_mutating`, `requires_hitl`, `risk_level`, `scopes_required`, `permitted_agent_roles`, and `tool_schema_version`
- Error responses use THS codes consistently
- No write path bypasses dry-run or idempotency checks

**Exit criteria**
- Spec and implementation agree on tool contract shape
- THS error format is documented and test-covered
- No unresolved ambiguity remains around safety classification

---

### Phase 1 — Core MCP Compliance

**Objectives**
- Make the MCP surface fully deterministic and THS-aligned.
- Ensure read tools, resources, and prompts behave consistently.
- Tighten request validation and response typing.

**Deliverables**
- Finalized read/write handlers
- Strict schema validation for tool inputs and outputs
- Resource serialization rules and freshness labels
- Prompt workflows that only call bounded tools
- Audit-friendly request IDs and log correlation

**Testing strategy**
- Unit tests for validation, normalization, and safety gates
- Integration tests for each tool with mocked upstream responses
- Resource tests for cache hit/miss and stale behavior
- Prompt tests for tool sequencing expectations

**Quality gates**
- Read paths return deterministic envelopes
- Write paths fail closed on missing validation
- No prompt contains unbounded execution instructions

**Exit criteria**
- All current tools pass contract tests
- All resources validate against documented MIME/URI behavior
- Prompts are documented and regression-tested

---

### Phase 2 — Performance, Reliability, and Observability

**Objectives**
- Introduce the full cache architecture and observability stack.
- Add upstream resilience controls.
- Make the server production-operator friendly.

**Deliverables**
- L1 in-process cache + L2 Redis cache
- Cache invalidation and stale-data policy
- Circuit breaker and retry budgets for Braiins upstream calls
- Prometheus metrics and OpenTelemetry tracing
- Structured JSON logs with correlation IDs
- Readiness and liveness checks aligned to runtime dependencies

**Testing strategy**
- Cache TTL and invalidation tests
- Failure-mode tests for upstream outage and stale fallback
- Metrics emission tests
- Load tests for concurrent reads and write bursts
- Logging assertions for secret redaction

**Quality gates**
- p99 latency targets are met for cached reads and dry-run writes
- Cache hit ratio is measurable and stable
- Observability emits required THS metrics and labels
- Security-sensitive fields are redacted from logs

**Exit criteria**
- Operational dashboards and alerts exist
- Read behavior degrades gracefully under upstream faults
- Performance is repeatable across local and staging environments

---

### Phase 3 — Deployment, A2A, and Production Rollout

**Objectives**
- Add deployment automation and discovery registration.
- Publish an Agent Card for A2A routing.
- Enable production rollout with repeatable infrastructure.

**Deliverables**
- `ansible/` deployment structure at repo root
- `agent-card.json` generation and validation
- Discovery registration flow for A2A and MCP endpoints
- Rollback and maintenance playbooks
- Production rollout checklist and smoke tests

**Testing strategy**
- Ansible syntax and idempotency checks
- Agent Card schema validation
- Discovery endpoint health checks
- Staged rollout smoke tests
- Rollback drill validation

**Quality gates**
- Deployment is reproducible from Ansible
- Agent Card is schema-valid and discoverable
- Rollout does not bypass security or observability gates
- Rollback can restore the last known good version

**Exit criteria**
- Production deployment is documented and automatable
- Discovery endpoints and A2A metadata are live
- Rollback and maintenance procedures are verified

---

## 4. Testing Strategy

### 4.1 Unit Tests
- Schema validation
- Safety gating
- Idempotency behavior
- Error mapping and envelope construction
- Unit normalization logic

### 4.2 Integration Tests
- MCP tool round-trips
- Resource reads and cache behavior
- Dry-run and live write flows
- Upstream error propagation

### 4.3 Security Tests
- Secret redaction
- Scope and role enforcement
- HITL gating
- Replay and duplicate request handling

### 4.4 Operational Tests
- Health/readiness probes
- Metrics exposure
- Alert rule presence
- Deployment and rollback paths

---

## 5. CI/CD Pipeline

### 5.1 Continuous Integration

Pipeline stages:
1. Format and lint
2. Type / schema validation
3. Unit tests
4. Integration tests
5. Security scans
6. Packaging validation

### 5.2 Continuous Delivery

Pipeline stages:
1. Build artifact
2. Generate SBOM
3. Produce deployment manifests
4. Publish container image
5. Run staging smoke tests
6. Promote to production on approval

### 5.3 Required Checks
- `ruff` / formatting
- `mypy` / type checking
- test suite pass
- secret scan pass
- container vulnerability scan pass
- schema / contract tests pass

---

## 6. Environment Variables

### 6.1 Runtime Configuration

| Variable | Purpose |
|---|---|
| `BRAIINS_API_KEY` | Braiins API key |
| `BRAIINS_API_SECRET` | Braiins API secret |
| `BRAIINS_API_BASE_URL` | Braiins API endpoint |
| `BRAIINS_MODE` | `read_only` or `trading` |
| `BRAIINS_DRY_RUN_DEFAULT` | Default dry-run behavior |
| `MCP_SERVER_HOST` | Bind host |
| `MCP_SERVER_PORT` | Bind port |
| `REDIS_URL` | Redis cache / idempotency store |
| `DATABASE_URL` | PostgreSQL audit store |
| `LOG_LEVEL` | Logging level |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Trace export target |
| `MCP_SINGLE_TENANT_MODE` | Development auth bypass |
| `SINGLE_TENANT_API_KEY` | Local development key |

### 6.2 Deployment Inputs
- image tag
- environment name
- tenant config references
- cache sizing parameters
- alert routing targets

---

## 7. Deployment and Rollout Notes

- Deploy via Ansible, not ad hoc shell scripts.
- Verify discovery registration before marking deployment complete.
- Keep read-only and mutating tool policies explicit in every environment.
- Roll out first to staging, then production.
- Always confirm health, metrics, and audit log writes after deployment.

---

## 8. Acceptance Summary

The project is considered THS-aligned when:
- tool contracts include full THS metadata
- errors use `THS_ERR_*`
- cache and observability policies are documented and implemented
- Ansible deployment structure exists and is exercised
- A2A Agent Card publication is available for discovery
- CI/CD enforces quality and security gates
- production rollout is reproducible and rollback-safe
