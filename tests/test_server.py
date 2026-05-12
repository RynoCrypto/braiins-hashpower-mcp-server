"""Sanity tests for the MCP server scaffold."""

from braiins_hashpower_mcp.server import mcp


def test_mcp_instance_created() -> None:
    """Verify the FastMCP instance is initialized with the correct name."""
    assert mcp.name == "braiins_hashpower"
