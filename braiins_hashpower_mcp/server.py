"""FastMCP server entry point with SSE transport."""

import os

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("braiins_hashpower")

# TODO: register tools, resources, and prompts from submodules


def main() -> None:
    """Run the MCP server over SSE transport."""
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8765"))
    app = mcp.sse_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
