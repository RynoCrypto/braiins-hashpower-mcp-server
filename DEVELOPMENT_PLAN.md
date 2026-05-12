# Braiins Hashpower MCP Server — Development Plan

**Version:** 0.1  
**Status:** Phase 4 complete / Phase 5 pending  
**Last Updated:** 2026-05-12

---

## 1. Executive Summary

This plan moves `braiins-hashpower-mcp` from spec (README-only) to a production-grade MCP server. Execution is split into six phases: Foundation, Braiins API Client, MCP Server Core, Safety & Validation, Testing & Hardening, and Release Integration.

**Primary constraint:** All write operations default to `dry_run=true`. No exceptions.

---

## 2. Phase Breakdown

### Phase 1: Foundation — Project Scaffold & Tooling

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| 1.1 Initialize Python package structure | `braiins_hashpower_mcp/` tree per README layout | `python -c "import braiins_hashpower_mcp"` succeeds |
| 1.2 Write `pyproject.toml` | Dependencies pinned, dev extras declared, entry point for server | `pip install -e ".[dev]"` completes cleanly |
| 1.3 Create `.env.example` | All documented env vars present with sensible defaults | N/A |
| 1.4 Add pre-commit hooks | `ruff`, `mypy`, `pytest` hooks in `.pre-commit-config.yaml` | `pre-commit run --all-files` passes on empty scaffold |
| 1.5 Set up pytest + coverage | `pytest.ini` or `pyproject.toml` config, `pytest tests/` passes | Coverage baseline captured (will be low) |
| 1.6 Add `Makefile` or `task` scripts | `make test`, `make lint`, `make run` targets | All targets execute without error |

**Risk:** FastMCP SSE transport is still evolving. Mitigation: pin to a known-working minor version and track releases.

---

### Phase 2: Braiins API Client

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| 2.1 Implement HMAC auth in `auth.py` | `sign_request(method, path, body)` → headers dict | Unit tests verify signature matches Braiins spec |
| 2.2 Build async HTTP client in `client.py` | `BraiinsClient` class with `request()`, retry logic via `tenacity` | Mocked tests pass for GET/POST/DELETE |
| 2.3 Add settings cache in `settings_cache.py` | TTL cache for `/spot/settings`, refresh on expiry | Cache hit/miss tests pass; TTL respected |
| 2.4 Map Braiins error codes in `errors.py` | `BraiinsError` exception hierarchy + `to_mcp_error()` mapper | All documented error codes have mapped equivalents |
| 2.5 Implement market data in `market.py` | `get_settings()`, `get_orderbook()` wrappers | Integration tests against Braiins sandbox or recorded cassettes |
| 2.6 Implement order ops in `orders.py` | `list_orders()`, `create_bid()`, `cancel_order()` wrappers | Same as above |
| 2.7 Write `SPEC.md` | Formal API contract: endpoints, auth scheme, rate limits, error codes | Reviewed against Braiins public docs |

**Risk:** Braiins API may have undocumented rate limits or behavioral edge cases. Mitigation: use `vcrpy` or `pytest-httpx` to record real responses early; run integration tests against live sandbox with low-frequency calls.

---

### Phase 3: MCP Server Core

| Task | Deliverable | Exit Criteria | Status |
|------|-------------|---------------|--------|
| 3.1 Define Pydantic schemas in `schemas.py` | Input/output models for all tools and resources | `mypy` passes; all fields have types and descriptions | Done |
| 3.2 Implement tools in `mcp/tools.py` | All 7 tools decorated with `@mcp.tool()` | Client can list tools via SSE; schema introspection works | Done |
| 3.3 Implement resources in `mcp/resources.py` | All 5 resources decorated with `@mcp.resource()` | `read_resource(uri)` returns correct payload per URI | Done |
| 3.4 Implement prompts in `mcp/prompts.py` | All 3 prompts decorated with `@mcp.prompt()` | Prompt templates render with injected context | Done |
| 3.5 Wire FastMCP + SSE in `server.py` | `mcp = FastMCP(...)`; SSE endpoint exposed via `uvicorn` | `GET /sse` returns 200; MCP inspector connects | Done |
| 3.6 Add health/readiness endpoints | `/health` and `/ready` for deployment orchestrators | Return 200 when initialized; 503 if not ready | Done |

**Completed on:** 2026-05-12

**Risk:** MCP protocol version drift. Mitigation: pin `mcp[server]` to exact version; test against `langchain-mcp-adapters` before any bump.

---

### Phase 4: Safety & Validation Layer

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| 4.1 Implement `dry_run` gate in `approvals.py` | All write tools reject if `dry_run=true` (default) | Unit tests: bid with default params returns dry-run confirmation |
| 4.2 Implement `read_only` mode | `BRAIINS_MODE=read_only` blocks all writes at decorator level | Unit tests: write tools return 403-equivalent error |
| 4.3 Build spend cap validator in `limits.py` | `BRAIINS_MAX_ORDER_USD` enforced server-side | Orders exceeding cap rejected before API call |
| 4.4 Build unit normalizer in `validators.py` | Price/amount validated against live `/spot/settings` units | Invalid units rejected; valid units pass |
| 4.5 Add idempotency key support | `client_order_id` required for `create_bid`; duplicates rejected | Double-submit with same ID returns original result |
| 4.6 Log all write attempts | Structured JSON logs: tool, params, dry_run flag, outcome | Logs auditable; no secrets leaked |

**Risk:** Safety layer bypass via direct API client use. Mitigation: client is internal-only; no public exports. All writes go through tool layer.

---

### Phase 5: Testing & Hardening

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| 5.1 Unit tests for auth | HMAC signature correctness, secret handling | 100% branch coverage on `auth.py` |
| 5.2 Unit tests for client | Retry logic, timeout handling, error raising | Mock server tests pass |
| 5.3 Unit tests for safety layer | Dry run, read_only, spend caps, validators | All edge cases covered |
| 5.4 Integration tests for tools | End-to-end: tool call → Braiins mock → response | `pytest tests/test_tools.py` passes |
| 5.5 Integration tests for resources | Resource reads with cache warm/cold states | `pytest tests/test_resources.py` passes |
| 5.6 Load test SSE endpoint | `locust` or `pytest-asyncio` concurrent clients | 100 concurrent connections stable; no memory leak |
| 5.7 Security audit | Scan for secret leakage, injection vectors, log exposure | `bandit` and `semgrep` clean |
| 5.8 Documentation review | README, SPEC, inline docstrings accurate | No drift between code and docs |

**Target metrics:**
- Test coverage: ≥ 85% overall, 100% on safety layer
- Lint: `ruff check .` clean
- Types: `mypy` strict mode clean

---

### Phase 6: Release Integration

| Task | Deliverable | Exit Criteria |
|------|-------------|---------------|
| 6.1 Add `examples/langgraph_agent.py` | Runnable agent script per README snippet | Executes without runtime errors against local server |
| 6.2 Add `examples/claude_desktop_config.json` | Verified config for Claude Desktop / Cursor | JSON valid; paths correct |
| 6.3 Write `CHANGELOG.md` | v0.1.0 entry with feature list and known issues | Published |
| 6.4 Tag `v0.1.0` | Git tag + GitHub release | CI passes on tag |
| 6.5 Publish to PyPI | `pip install braiins-hashpower-mcp` works | Package installable; entry point executable |
| 6.6 Docker image (optional) | `Dockerfile` + `docker-compose.yml` | `docker compose up` starts server on `:8765` |

---

## 3. Sprint Mapping

| Sprint | Duration | Focus | Key Deliverables |
|--------|----------|-------|------------------|
| 1 | Week 1 | Phase 1 + Phase 2 scaffold | Project runs, auth signs, client requests |
| 2 | Week 2 | Phase 2 completion + Phase 3 start | All Braiins endpoints wrapped; first tool exposed |
| 3 | Week 3 | Phase 3 completion | All tools, resources, prompts live; SSE stable |
| 4 | Week 4 | Phase 4 | Safety layer enforced; dry_run default locked |
| 5 | Week 5 | Phase 5 | Test suite green; coverage ≥ 85%; security audit clean |
| 6 | Week 6 | Phase 6 + buffer | Examples verified, v0.1.0 tagged, PyPI published |

**Buffer:** Sprint 6 includes 2 days slack for review and bugfix.

---

## 4. Milestones & Exit Criteria

| Milestone | Date Target | Exit Criteria |
|-----------|-------------|---------------|
| M1: Scaffold Ready | End Sprint 1 | `make test` and `make lint` pass on CI |
| M2: API Client Complete | End Sprint 2 | All documented endpoints callable via internal client |
| M3: MCP Surface Live | End Sprint 3 | `langchain-mcp-adapters` connects; tool calls succeed |
| M4: Safety Hardened | End Sprint 4 | Penetration-style tests confirm dry_run and caps work |
| M5: Release Candidate | End Sprint 5 | Tag `v0.1.0-rc1`; no open P1/P2 bugs |
| M6: General Availability | End Sprint 6 | PyPI publish; README install instructions verified on clean machine |

---

## 5. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Braiins API changes during dev | Medium | High | Abstract client layer; record cassettes; weekly API diff check |
| FastMCP SSE transport breaks | Low | High | Pin version; subscribe to repo releases; maintain stdio fallback branch |
| HMAC auth subtlety (timestamp drift, encoding) | Medium | High | Record live signatures; compare byte-for-byte in tests |
| Rate limit hits during integration tests | Medium | Medium | Use mocked responses for CI; live tests gated behind `--live` flag |
| No Braiins sandbox environment | Medium | High | Request sandbox credentials; fallback to `vcrpy` cassettes from manual runs |
| Safety layer bypass bug | Low | Critical | 100% branch coverage on safety code; red-team review before M4 |

---

## 6. Development Environment

```bash
# Clone
cd ~/projects/braiins-hashpower-mcp-server

# Install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env
# edit .env with credentials

# Run checks
make lint        # ruff + mypy
make test        # pytest with coverage
make run         # uvicorn with reload
```

**Required:** Python 3.11+. `asyncio` default loop must be `uvloop` in production (enforced in `Dockerfile`).

---

## 7. Definition of Done

A task is done when:

1. Code is written, typed, and lint-clean.
2. Unit/integration tests pass; new code has ≥ 85% coverage.
3. Safety-relevant code has 100% branch coverage.
4. Documentation (docstrings, README, SPEC) is updated if behavior changed.
5. PR is reviewed and merged to `main`.
6. CI pipeline green on `main`.

---

## 8. Post-Launch Roadmap (Post-v0.1.0)

| Feature | Priority | Notes |
|---------|----------|-------|
| WebSocket transport for lower latency | Medium | MCP spec may standardize; evaluate |
| Hashrate delivery streaming resource | Medium | SSE push on delivery state changes |
| Multi-account support | Low | `BRAIINS_API_KEY_N` pattern or config file |
| Prometheus metrics endpoint | Low | `/metrics` for order latency, cache hit rate |
| CLI companion tool | Low | `braiins-mcp` CLI for manual API calls |

---

## 9. Open Questions

1. Does Braiins provide a sandbox/testnet API environment? If not, integration tests rely on recorded cassettes.
2. What is the exact HMAC scheme (SHA-256 vs SHA-512, header names, timestamp format)? Verify against live API before Sprint 2 ends.
3. Are there WebSocket or streaming endpoints for orderbook/deliveries that should be prioritized over REST polling?
4. What is the Braiins API rate limit? Document in `SPEC.md` once known.

---

*End of plan. Execute Phase 1, Task 1.1 to begin.*
