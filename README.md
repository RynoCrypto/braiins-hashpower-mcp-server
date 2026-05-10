# braiins-hashpower-mcp

An MCP (Model Context Protocol) server for the [Braiins Hashpower Network](https://hashpower.braiins.com) spot market API. Built with [FastMCP](https://github.com/jlowin/fastmcp) and served over **SSE transport**, with LangChain/LangGraph integration via the [`langchain-mcp-adapters`](https://github.com/langchain-ai/langchain-mcp-adapters) library.

> **Status:** Pre-release / Spec v0.1

***

## Overview

`braiins-hashpower-mcp` exposes Braiins Hashpower's spot-market API as a structured set of MCP tools, resources, and prompts that AI agents (LangGraph, Claude, Cursor, etc.) can call to:

- Inspect real-time market settings and price/unit metadata
- Query spot orderbook depth
- Manage their own open and historical orders
- Place and cancel spot bids
- Review account summaries and hashrate delivery state

All API credentials stay server-side. The model never sees raw secrets. Order entry is gated behind a `dry_run=true` default and an explicit safety validation layer.

***

## Architecture

```
┌─────────────────────────────────────────────┐
│              AI Agent / Client              │
│  (LangGraph, Claude Desktop, Cursor, etc.)  │
└──────────────────┬──────────────────────────┘
                   │  SSE transport
                   │  (MCP protocol)
┌──────────────────▼──────────────────────────┐
│         braiins-hashpower-mcp               │
│         FastMCP + SSE Server                │
│                                             │
│  ┌────────────┐  ┌───────────┐  ┌────────┐ │
│  │   Tools    │  │ Resources │  │Prompts │ │
│  └────────────┘  └───────────┘  └────────┘ │
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │         Safety Layer                 │  │
│  │  (unit normalization, spend caps,    │  │
│  │   dry_run gate, approval flags)      │  │
│  └──────────────────────────────────────┘  │
│                                             │
│  ┌──────────────────────────────────────┐  │
│  │     Braiins API Client               │  │
│  │     (httpx, settings cache)          │  │
│  └──────────────────────────────────────┘  │
└──────────────────┬──────────────────────────┘
                   │  HTTPS REST
┌──────────────────▼──────────────────────────┐
│     Braiins Hashpower API                   │
│     https://hashpower.braiins.com/api/      │
└─────────────────────────────────────────────┘
```

***

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-org/braiins-hashpower-mcp.git
cd braiins-hashpower-mcp
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
BRAIINS_API_BASE_URL=https://hashpower.braiins.com/api
BRAIINS_API_KEY=your_api_key_here
BRAIINS_API_SECRET=your_api_secret_here
BRAIINS_MODE=read_only          # read_only | trading
BRAIINS_DRY_RUN_DEFAULT=true
BRAIINS_MAX_ORDER_USD=500
MCP_SERVER_HOST=0.0.0.0
MCP_SERVER_PORT=8765
```

### 3. Run the server

```bash
python -m braiins_hashpower_mcp.server
```

The server starts an SSE endpoint at:

```
http://localhost:8765/sse
```

***

## Connecting a LangGraph Agent

Install the adapter:

```bash
pip install langchain-mcp-adapters langgraph "langchain[openai]"
```

Connect with `MultiServerMCPClient`:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

client = MultiServerMCPClient(
    {
        "braiins": {
            "transport": "sse",
            "url": "http://localhost:8765/sse",
            "headers": {
                # Optional: per-request trace ID
                "X-Trace-Id": "my-agent-session-001"
            }
        }
    }
)

tools = await client.get_tools()
agent = create_react_agent("openai:gpt-4.1", tools)

response = await agent.ainvoke({
    "messages": "What are the current spot market settings and what is the orderbook depth?"
})
```

### Using with LangGraph StateGraph

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.chat_models import init_chat_model

model = init_chat_model("openai:gpt-4.1")

client = MultiServerMCPClient(
    {
        "braiins": {
            "transport": "sse",
            "url": "http://localhost:8765/sse",
        }
    }
)
tools = await client.get_tools()

def call_model(state: MessagesState):
    return {"messages": model.bind_tools(tools).invoke(state["messages"])}

builder = StateGraph(MessagesState)
builder.add_node(call_model)
builder.add_node(ToolNode(tools))
builder.add_edge(START, "call_model")
builder.add_conditional_edges("call_model", tools_condition)
builder.add_edge("tools", "call_model")
graph = builder.compile()
```

### Using with Claude Desktop / Cursor

Add to your MCP config:

```json
{
  "mcpServers": {
    "braiins-hashpower": {
      "transport": "sse",
      "url": "http://localhost:8765/sse"
    }
  }
}
```

***

## Available Tools

| Tool | Description | Trust Level |
|------|-------------|-------------|
| `get_market_settings` | Fetch spot market unit metadata and price settings | Safe read |
| `get_orderbook` | Return current bid/ask depth | Safe read |
| `list_orders` | List open, filled, or canceled orders | Safe read |
| `get_account_summary` | Return account balance and exposure snapshot | Safe read |
| `get_deliveries` | Fetch hashrate delivery and allocation state | Safe read |
| `create_bid` | Place a spot-market bid (dry_run=true by default) | Sensitive write |
| `cancel_order` | Cancel an order by ID | Sensitive write |

***

## Available Resources

| URI | Description |
|-----|-------------|
| `braiins://spot/settings` | Cached spot market settings (unit metadata, price units) |
| `braiins://account/orders/open` | Read-only snapshot of open orders |
| `braiins://account/orders/history` | Recent trade history |
| `braiins://account/summary` | Account balance and active positions |
| `braiins://docs/error-codes` | Normalized Braiins API error catalog |

***

## Available Prompts

| Prompt | Description |
|--------|-------------|
| `place-conservative-bid` | Guided workflow: read settings → inspect book → compose bounded bid |
| `review-open-orders` | Summarize exposure and recommend actions without mutating state |
| `explain-price-units` | Explain Braiins spot-market units and pricing semantics |

***

## Project Layout

```
braiins-hashpower-mcp/
├── braiins_hashpower_mcp/
│   ├── __init__.py
│   ├── server.py               # FastMCP server entry point + SSE transport
│   ├── mcp/
│   │   ├── tools.py            # @mcp.tool() definitions
│   │   ├── resources.py        # @mcp.resource() definitions
│   │   ├── prompts.py          # @mcp.prompt() definitions
│   │   └── schemas.py          # Pydantic input/output models
│   ├── braiins/
│   │   ├── client.py           # httpx async Braiins REST client
│   │   ├── auth.py             # HMAC/API key signing
│   │   ├── settings_cache.py   # /spot/settings TTL cache
│   │   ├── orders.py           # Order CRUD operations
│   │   ├── market.py           # Orderbook and market data
│   │   └── errors.py           # Braiins error → MCP error mapping
│   └── safety/
│       ├── approvals.py        # Write-action gate flags
│       ├── limits.py           # Max notional, allowed markets
│       └── validators.py       # Unit normalization, pre-flight checks
├── tests/
│   ├── test_tools.py
│   ├── test_safety.py
│   └── test_client.py
├── examples/
│   ├── langgraph_agent.py
│   └── claude_desktop_config.json
├── .env.example
├── pyproject.toml
├── README.md
└── SPEC.md
```

***

## Safety Model

`create_bid` and `cancel_order` are **sensitive writes**. The server enforces:

- `dry_run=true` as the default for all order-entry tools until explicitly overridden.
- Market setting validation: price and amount are validated against live `/spot/settings` units before any order is submitted.
- `BRAIINS_MAX_ORDER_USD` cap: orders exceeding this value are rejected server-side before touching the API.
- `BRAIINS_MODE=read_only`: when set, all write tools return an error immediately.
- `client_order_id` idempotency support to prevent duplicate submissions.

***

## Development

```bash
# Run tests
pytest tests/ -v

# Run with auto-reload
uvicorn braiins_hashpower_mcp.server:app --reload --port 8765

# Lint
ruff check . && mypy braiins_hashpower_mcp/
```

***

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp[server]` | FastMCP and MCP protocol primitives |
| `httpx` | Async HTTP client for Braiins API |
| `fastapi` + `uvicorn` | SSE transport host |
| `pydantic` | Schema validation |
| `tenacity` | Retry logic for transient API errors |
| `python-dotenv` | Environment config |
| `langchain-mcp-adapters` | LangChain/LangGraph integration (client-side) |

***

## License

MIT

***

## Related

- [Braiins Hashpower API Reference](https://hashpower.braiins.com/api/)
- [Braiins Academy: Public API](https://academy.braiins.com/en/braiins-hashpower/api/)
- [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- [Model Context Protocol Specification](https://modelcontextprotocol.io)
