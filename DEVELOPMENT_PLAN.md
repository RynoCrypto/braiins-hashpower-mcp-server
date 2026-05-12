# Braiins Hashpower MCP Server — Development Plan

## Project Overview

Model Context Protocol (MCP) server exposing the Braiins Hashpower Market API. Provides LLM-accessible tools, resources, and prompts for managing Bitcoin hashpower bids and market data.

**Repository**: `~/projects/braiins-hashpower-mcp-server/`
**Language**: Python 3.13
**Framework**: FastMCP + httpx
**Transport**: SSE (Server-Sent Events)

---

## Architecture

```
braiins_hashpower_mcp/
├── __init__.py
├── server.py              # FastMCP app, lifespan, health/ready handlers, main()
├── braiins/
│   ├── auth.py            # HMAC-less key header auth
│   ├── client.py          # Async Braiins API client with tenacity retries
│   ├── errors.py          # Exception hierarchy (auth, validation, rate-limit, server)
│   ├── market.py          # Market data helpers (settings, orderbook, trades, fees, stats)
│   ├── orders.py          # CRUD helpers for bids (create, edit, cancel, list)
│   └── settings_cache.py  # TTL cache for spot settings
├── mcp/
│   ├── prompts.py         # MCP prompts (conservative bid, review orders, price units)
│   ├── resources.py       # MCP resources (settings, open orders, history, error codes)
│   ├── schemas.py         # Pydantic request/response models
│   └── tools.py           # MCP tools (list_orders, create_bid, cancel_order, get_market_data)
└── safety/
    ├── __init__.py
    ├── approvals.py       # Dry-run and read-only gating
    ├── limits.py          # Bid amount/price ceiling checks
    └── validators.py      # Input validation (upstream IDs, price ranges, idempotency)
```

---

## Development Phases

### Phase 1 — Foundation
- [x] Project scaffolding (pyproject.toml, pytest, ruff, mypy)
- [x] Braiins API client with retry/timeout logic
- [x] Authentication module (API key headers)
- [x] Exception hierarchy mapped to HTTP status codes
- [x] Settings cache with TTL invalidation

### Phase 2 — Business Logic
- [x] Market data helpers (settings, orderbook, trades, fees, stats)
- [x] Order lifecycle helpers (list, create, edit, cancel)
- [x] Safety layer (validators, limits, approvals, idempotency)
- [x] Error code documentation resource

### Phase 3 — MCP Integration
- [x] FastMCP server with SSE transport
- [x] Tool definitions with Pydantic schemas
- [x] Resource endpoints (spot settings, orders, history)
- [x] Prompt templates for bid placement and review
- [x] Health (`/health`) and readiness (`/ready`) probes

### Phase 4 — Configuration & Deployment
- [x] Environment-based configuration (API keys, base URL, host/port, mode)
- [x] Docker support (Dockerfile, docker-compose)
- [x] Makefile with common targets (install, test, lint, typecheck, run)
- [x] README with setup and usage instructions

### Phase 5 — Testing & Quality Assurance
- [x] 5.1 Unit tests for auth.py — 100% branch coverage
- [x] 5.2 Unit tests for client.py — retry, timeout, errors, mock server
- [x] 5.3 Unit tests for safety layer — limits, validators, approvals, idempotency
- [x] 5.4 Integration tests for tools (test_tools.py) — e2e with mocked Braiins
- [x] 5.5 Integration tests for resources (test_resources.py) — cache warm/cold
- [x] 5.6 Load test SSE endpoint — 100 concurrent connections (skippable if server offline)
- [x] 5.7 Security audit — bandit + semgrep
- [x] 5.8 Documentation review — README/SPEC/docstring accuracy
- [x] 5.9 Full test suite, coverage report, lint, type checks

**Coverage Result**: 99% (514 statements, 1 miss on `if __name__ == "__main__": main()`)
**Test Count**: 193 passed, 2 skipped
**Lint**: ruff clean
**Type Check**: mypy clean (18 source files)
**Security**: bandit clean (0 findings), semgrep clean (p/ci ruleset)

### Phase 6 — CI/CD & Release Automation
- [x] 6.1 GitHub Actions CI pipeline (lint, typecheck, test matrix 3.11–3.13, security scan)
- [x] 6.2 GitHub Actions Release pipeline (build on tag, publish to PyPI via OIDC)
- [x] 6.3 Coverage upload to Codecov
- [x] 6.4 Artifact retention for security reports

**CI Status**: `.github/workflows/ci.yml` — runs on push/PR to `main`
**Release Status**: `.github/workflows/release.yml` — triggers on `v*` tags, trusted publishing to PyPI

---

## Tool Inventory

| Tool | Action | Safety Gate |
|------|--------|-------------|
| `list_orders` | Read | — |
| `create_bid` | Write | Validation → Limit → Approval → Dry-run optional |
| `cancel_order` | Write | Validation → Approval → Dry-run optional |
| `get_market_data` | Read | — |

## Resource Inventory

| Resource | URI | Type |
|----------|-----|------|
| Spot Settings | `braiins://spot/settings` | Cached market config |
| Open Orders | `braiins://account/orders/open` | Live list |
| Order History | `braiins://account/orders/history` | Live list |
| Error Codes | `braiins://docs/error-codes` | Static reference |
| Account Summary | `braiins://account/summary` | Placeholder |

## Prompt Inventory

| Prompt | Purpose |
|--------|---------|
| `place_conservative_bid` | Guide user through low-risk bid placement |
| `review_open_orders` | Summarize and suggest actions on open orders |
| `explain_price_units` | Document sat/PH/day pricing model |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SINGLE_TENANT_API_KEY` | — | Primary API key (also accepts `BRAIINS_API_KEY`) |
| `BRAIINS_API_BASE_URL` | `https://api.braiins.com/v1` | Braiins API endpoint |
| `BRAIINS_MODE` | `read_write` | `read_write` or `read_only` |
| `BRAIINS_DRY_RUN_DEFAULT` | `True` | Default dry-run flag for write tools |
| `MCP_SERVER_HOST` | `0.0.0.0` | SSE bind address |
| `MCP_SERVER_PORT` | `8765` | SSE listen port |

---

## Makefile Targets

```bash
make install      # uv sync --all-extras
make test         # pytest --cov=braiins_hashpower_mcp
make lint         # ruff check .
make typecheck    # mypy braiins_hashpower_mcp/
make format       # ruff format .
make run          # python -m braiins_hashpower_mcp.server
make docker       # docker-compose up --build
```

---

## Security Hardening

1. **No secrets in logs** — `_sanitize_params` redacts `api_secret`, `password`, `token`.
2. **Dry-run by default** — All write tools require explicit `dry_run=False` to mutate state.
3. **Read-only mode** — `BRAIINS_MODE=read_only` blocks write tools at the gate.
4. **Bid limits** — Ceiling checks prevent accidental oversized bids.
5. **Idempotency cache** — 60-second deduplication window for identical write requests.
6. **Tenacity retries** — Exponential backoff on network errors; no retry on 4xx.
7. **Bandit clean** — B110 and B104 findings resolved or documented (`# nosec`).

---

## Next Steps / Future Work

- OAuth 2.0 / multi-tenant auth (currently single API key)
- Webhook push for order status changes
- Historical P&L resource endpoint
- Batch order operations (create multiple bids atomically)
- Prometheus metrics export

---

## Changelog

| Date | Milestone |
|------|-----------|
| 2026-05-12 | Phase 5 complete — 99% test coverage, security audit passed, lint/type clean |
| 2026-05-12 | Phase 6 complete — CI/CD pipelines (ci.yml + release.yml), PyPI trusted publishing configured |
