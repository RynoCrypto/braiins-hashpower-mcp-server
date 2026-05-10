# SPEC.md — Braiins Hashpower MCP Server

**Version:** 0.1  
**Transport:** SSE (Server-Sent Events)  
**Framework:** FastMCP (`mcp[server]`) + LangChain MCP Adapters  
**API Target:** [Braiins Hashpower Network](https://hashpower.braiins.com/api/)  
**Language:** Python 3.11+

---

## 1. Purpose and Scope

This document specifies the design of an MCP server that wraps the Braiins Hashpower Network spot-market REST API. The server exposes structured **tools**, **resources**, and **prompts** to AI agent clients (LangGraph agents, Claude, Cursor, etc.) via SSE transport.

### Goals

- Provide a safe, agent-friendly interface for reading Braiins spot-market data and managing orders.
- Enforce server-side unit normalization using `/spot/settings` metadata before any order is submitted.
- Guarantee credentials never leave the server process.
- Default to `dry_run=true` on all write tools until explicitly disabled by the operator.
- Be compatible with `MultiServerMCPClient` from `langchain-mcp-adapters` over SSE.

### Out of Scope (v0.1)

- Futures or non-spot market types.
- Webhook or push-based order status notifications.
- Multi-account / sub-account management.
- Portfolio analytics or charting.

---

## 2. Transport: SSE

The server uses SSE (Server-Sent Events) transport, which is one of the two HTTP-based MCP transports supported by `langchain-mcp-adapters` (alongside `streamable_http`). SSE is chosen because:

- It is widely supported across MCP clients including Claude Desktop, Cursor, and LangGraph agents.
- The `langchain-mcp-adapters` `MultiServerMCPClient` supports it natively with `"transport": "sse"`.
- Runtime headers (e.g., Authorization, trace IDs) can be injected per-connection.
- It is stateless-friendly for horizontally scaled deployments.

### Server Endpoint

```
GET http://{host}:{port}/sse
```

Default: `http://0.0.0.0:8765/sse`

### Client Configuration (`langchain-mcp-adapters`)

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "braiins": {
            "transport": "sse",
            "url": "http://localhost:8765/sse",
            "headers": {
                "X-Trace-Id": "optional-trace-header"
            }
        }
    }
)
tools = await client.get_tools()
```

> Only `sse` and `streamable_http` transports support runtime headers in `langchain-mcp-adapters`. Headers are passed with every HTTP request to the MCP server.

---

## 3. Server Implementation

### Framework

The server is implemented using **FastMCP** from the `mcp` Python SDK:

```python
# braiins_hashpower_mcp/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("BraiinsHashpower")

# Tools, resources, and prompts are registered via decorators
# (see sections 4, 5, 6)

if __name__ == "__main__":
    mcp.run(transport="sse")
```

FastMCP handles:
- MCP protocol handshake and capability negotiation.
- Tool/resource/prompt registration and dispatch.
- SSE connection lifecycle.

The SSE transport is hosted inside a FastAPI/Uvicorn application automatically by FastMCP.

---

## 4. Tools

Tools are **model-invoked actions**. The model calls them to retrieve data or perform mutations. All tools return a normalized response envelope.

### 4.1 Response Envelope

Every tool returns a JSON object matching:

```python
class MCPToolResponse(BaseModel):
    success: bool
    data: dict | list | None
    warnings: list[str] = []
    error: str | None = None
    request_id: str | None = None
    raw_api_status: int | None = None
```

### 4.2 Tool Definitions

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
**Caching:** 60-second TTL in `settings_cache.py`  
**Mapped endpoint:** `GET /spot/settings`

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
| `market` | `"spot"` | `"spot"` | Market identifier (only spot supported in v0.1) |
| `depth` | `int` | `20` | Number of levels to return per side |

**Trust level:** Safe read  
**Mapped endpoint:** `GET /spot/orderbook` or equivalent in Swagger spec

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
    Return a paginated list of the authenticated user's orders.
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
**Mapped endpoint:** `GET /spot/orders` or `/orders` per Swagger

---

#### `get_account_summary`

Return balance, exposure, and account-level metadata.

```python
@mcp.tool()
async def get_account_summary() -> MCPToolResponse:
    """
    Return the authenticated account's current balance, open order
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
**Mapped endpoint:** `GET /deliveries` or equivalent per Swagger

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
    """
```

**Input schema:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `amount` | `float` | required | Bid size in `hr_unit` from settings |
| `price` | `float` | required | Bid price in `price_sat` from settings |
| `market` | `"spot"` | `"spot"` | Market identifier |
| `client_order_id` | `str` | auto-generated | Idempotency key |
| `dry_run` | `bool` | `true` | Preview without submitting if true |

**Trust level:** Sensitive write (requires `BRAIINS_MODE=trading`)  
**Pre-flight validation:**
1. Fetch or use cached `/spot/settings`.
2. Validate `amount` within `min_amount`/`max_amount` bounds from settings.
3. Validate `price` is positive and within reasonable bounds.
4. Check `amount * price` ≤ `BRAIINS_MAX_ORDER_USD` (converted).
5. Reject if `BRAIINS_MODE=read_only`.
6. If `dry_run=false`, require `BRAIINS_DRY_RUN_DEFAULT=false` in env or explicit override.

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
    """
```

**Input schema:**
| Field | Type | Description |
|-------|------|-------------|
| `order_id` | `str` | The order ID to cancel |

**Trust level:** Sensitive write (requires `BRAIINS_MODE=trading`)  
**Mapped endpoint:** `DELETE /spot/orders/{order_id}` or equivalent per Swagger

---

## 5. Resources

Resources are **application-exposed context** that clients and models can read. They use URI addressing and are suitable for caching, pre-loading context, and providing stable reference data.

### Resource Definitions

| URI | MIME Type | TTL | Description |
|-----|-----------|-----|-------------|
| `braiins://spot/settings` | `application/json` | 60s | Spot market settings and unit metadata |
| `braiins://account/orders/open` | `application/json` | 10s | Snapshot of currently open orders |
| `braiins://account/orders/history` | `application/json` | 60s | Last 50 filled/canceled orders |
| `braiins://account/summary` | `application/json` | 30s | Account balance and exposure |
| `braiins://docs/error-codes` | `application/json` | static | Normalized Braiins API error catalog |

```python
@mcp.resource("braiins://spot/settings")
async def resource_spot_settings() -> str:
    """Current Braiins Hashpower spot market settings including
    price units (price_sat) and hashrate units (hr_unit)."""
    settings = await get_cached_settings()
    return settings.model_dump_json()

@mcp.resource("braiins://account/orders/open")
async def resource_open_orders() -> str:
    """Read-only snapshot of the authenticated account's open orders."""
    orders = await braiins_client.list_orders(status=["open"])
    return json.dumps(orders)
```

---

## 6. Prompts

Prompts are **reusable user-invoked workflows** that guide the agent through multi-step tasks. They do not call tools directly but compose instructions that lead the agent to call the right tools in sequence.

### Prompt Definitions

---

#### `place-conservative-bid`

```python
@mcp.prompt()
def prompt_conservative_bid() -> str:
    """
    Guided workflow for placing a conservative spot bid.
    Steps:
    1. Call get_market_settings to understand current units.
    2. Call get_orderbook to inspect current depth and mid-market price.
    3. Compose a bid below the current best ask by at least 1%.
    4. Call create_bid with dry_run=true to preview.
    5. Ask the user to confirm before setting dry_run=false.
    """
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
    """
    Summarize open order exposure and recommend actions without
    mutating any state.
    """
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
    """
    Explain Braiins Hashpower spot-market units and pricing semantics
    to the user before they place any order.
    """
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

## 7. Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BRAIINS_API_BASE_URL` | Yes | — | `https://hashpower.braiins.com/api` |
| `BRAIINS_API_KEY` | Yes | — | Braiins API key |
| `BRAIINS_API_SECRET` | Yes | — | Braiins API secret for request signing |
| `BRAIINS_MODE` | No | `read_only` | `read_only` or `trading` |
| `BRAIINS_DRY_RUN_DEFAULT` | No | `true` | Default dry_run value for create_bid |
| `BRAIINS_MAX_ORDER_USD` | No | `500` | Max notional per order in USD |
| `BRAIINS_SETTINGS_CACHE_TTL` | No | `60` | /spot/settings cache TTL in seconds |
| `MCP_SERVER_HOST` | No | `0.0.0.0` | SSE server bind host |
| `MCP_SERVER_PORT` | No | `8765` | SSE server port |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

---

## 8. Safety Model

### Trust Tiers

| Tier | Tools | Gate |
|------|-------|------|
| Safe read | `get_market_settings`, `get_orderbook`, `list_orders`, `get_account_summary`, `get_deliveries` | No gate |
| Sensitive write | `create_bid`, `cancel_order` | `BRAIINS_MODE=trading` + `dry_run` default |
| Future: High-risk | Bulk cancel, ladder placement | Explicit `BRAIINS_ALLOW_BULK=true` (not in v0.1) |

### Pre-flight Validation Flow (create_bid)

```
create_bid called
     │
     ▼
BRAIINS_MODE == "read_only"?  ─── YES ──► Return error: "Server in read_only mode"
     │ NO
     ▼
Fetch /spot/settings (cached)
     │
     ▼
Validate amount within [min_amount, max_amount]
     │
     ▼
Validate price > 0 and within sanity bounds
     │
     ▼
Validate notional <= BRAIINS_MAX_ORDER_USD
     │
     ▼
dry_run == true?  ─── YES ──► Return preview (no API call)
     │ NO
     ▼
POST /spot/bid
     │
     ▼
Return MCPToolResponse
```

---

## 9. Error Handling

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

All tools return `success=False` with a human-readable `error` string and the `raw_api_status` code. The model should surface the `error` string to the user without exposing raw HTTP details.

---

## 10. Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastMCP instantiation, SSE transport startup, environment loading |
| `mcp/tools.py` | `@mcp.tool()` definitions; input parsing; delegate to braiins/ and safety/ |
| `mcp/resources.py` | `@mcp.resource()` definitions; TTL caching; serialization |
| `mcp/prompts.py` | `@mcp.prompt()` definitions; static prompt strings |
| `mcp/schemas.py` | Pydantic models for all tool inputs and `MCPToolResponse` |
| `braiins/client.py` | Async httpx client; base URL; timeout; retry via tenacity |
| `braiins/auth.py` | HMAC/API key request signing for Braiins API |
| `braiins/settings_cache.py` | TTL cache for `/spot/settings`; exposes `get_cached_settings()` |
| `braiins/orders.py` | `list_orders`, `create_bid`, `cancel_order` API calls |
| `braiins/market.py` | `get_orderbook`, `get_deliveries` API calls |
| `braiins/errors.py` | HTTP status → structured MCP error mapping |
| `safety/approvals.py` | `BRAIINS_MODE` check; write-action gate |
| `safety/limits.py` | `BRAIINS_MAX_ORDER_USD` enforcement |
| `safety/validators.py` | Unit normalization against settings; pre-flight amount/price checks |

---

## 11. Dependencies

```toml
[project]
name = "braiins-hashpower-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp[server]>=1.9.1",
    "httpx>=0.27.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "pydantic>=2.7.0",
    "tenacity>=8.3.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",       # httpx mock
    "ruff>=0.4",
    "mypy>=1.10",
    "langchain-mcp-adapters>=0.1.0",  # for integration tests
]
```

---

## 12. Testing Strategy

| Test Layer | Tool | Coverage |
|------------|------|---------|
| Unit: tool logic | pytest + respx | All 7 tools; success and error paths |
| Unit: safety validators | pytest | Boundary checks, `read_only` gate, spend cap |
| Unit: settings cache | pytest | TTL expiry, refresh behavior |
| Integration: SSE transport | pytest-asyncio + langchain-mcp-adapters | Full round-trip via `MultiServerMCPClient` |
| Integration: dry_run | pytest-asyncio | `create_bid` with dry_run=true never hits API |

---

## 13. Versioning and Roadmap

### v0.1 (this spec)
- SSE transport
- 7 tools (5 safe read, 2 sensitive write)
- 5 resources
- 3 prompts
- `dry_run` default, `read_only` mode, spend cap

### v0.2 (planned)
- `streamable_http` transport option
- Order replace/amend tool
- Approval flow integration (human-in-the-loop before live orders)
- Structured logging with `structlog`
- Docker image and Compose file

### v0.3 (planned)
- Hashrate ladder / DCA prompt
- Portfolio exposure resource
- Prometheus metrics endpoint
- Multi-account profile support

---

## References

- [Braiins Hashpower API Reference](https://hashpower.braiins.com/api/)
- [Braiins Academy: Public API](https://academy.braiins.com/en/braiins-hashpower/api/)
- [langchain-mcp-adapters GitHub](https://github.com/langchain-ai/langchain-mcp-adapters)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol Specification](https://modelcontextprotocol.io)
- [LangGraph Prebuilt Agents](https://langchain-ai.github.io/langgraph/reference/prebuilt/)
