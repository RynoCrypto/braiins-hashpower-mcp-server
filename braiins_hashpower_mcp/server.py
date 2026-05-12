"""FastMCP server entry point with SSE transport."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from braiins_hashpower_mcp.braiins.auth import BraiinsAuth
from braiins_hashpower_mcp.braiins.client import BraiinsClient
from braiins_hashpower_mcp.mcp.prompts import register_prompts
from braiins_hashpower_mcp.mcp.resources import register_resources
from braiins_hashpower_mcp.mcp.tools import register_tools

load_dotenv()

logger = logging.getLogger(__name__)


class ServerState:
    """Mutable server state shared across the lifespan."""

    def __init__(self) -> None:
        self.client: BraiinsClient | None = None


state = ServerState()


@asynccontextmanager
async def lifespan(mcp: FastMCP) -> Any:
    """Initialize the Braiins client and register handlers."""
    api_key = os.getenv("SINGLE_TENANT_API_KEY", os.getenv("BRAIINS_API_KEY", ""))
    if not api_key:
        logger.warning(
            "No API key found. Set SINGLE_TENANT_API_KEY or BRAIINS_API_KEY env var."
        )
    auth = BraiinsAuth(api_key)
    state.client = BraiinsClient(auth)
    if state.client is not None:
        register_tools(mcp, state.client)
        register_resources(mcp, state.client)
    register_prompts(mcp)
    logger.info("Braiins MCP server initialized")
    yield
    if state.client:
        await state.client.close()
    logger.info("Braiins MCP server shut down")


mcp = FastMCP("braiins_hashpower", lifespan=lifespan)


def _health_handler(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _ready_handler(_request: Request) -> JSONResponse:
    if state.client is None:
        return JSONResponse(
            {"status": "not_ready", "reason": "client_not_initialized"},
            status_code=503,
        )
    return JSONResponse({"status": "ready"})


def main() -> None:
    """Run the MCP server over SSE transport."""
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")  # nosec: B104
    port = int(os.getenv("MCP_SERVER_PORT", "8765"))
    app = mcp.sse_app()
    app.add_route("/health", _health_handler)
    app.add_route("/ready", _ready_handler)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
