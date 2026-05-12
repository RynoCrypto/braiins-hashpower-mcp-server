"""MCP resources exposing Braiins Hashpower data via URI addressing."""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from braiins_hashpower_mcp.braiins.client import BraiinsClient
from braiins_hashpower_mcp.braiins.errors import BraiinsError
from braiins_hashpower_mcp.braiins.market import (
    get_settings as _get_settings,
)
from braiins_hashpower_mcp.braiins.orders import (
    list_active_bids as _list_active_bids,
)
from braiins_hashpower_mcp.braiins.orders import (
    list_bids as _list_bids,
)

logger = logging.getLogger(__name__)

ERROR_CATALOG = {
    "400": "BraiinsValidationError — malformed request or invalid parameters.",
    "401": "BraiinsAuthError — invalid or missing API key.",
    "403": "BraiinsAuthError — insufficient permissions.",
    "404": "BraiinsError — requested resource not found.",
    "429": "BraiinsRateLimitError — rate limit exceeded; retry after backoff.",
    "500": "BraiinsServerError — internal Braiins API error.",
    "503": "BraiinsServerError — Braiins API temporarily unavailable.",
}


def register_resources(mcp: FastMCP, client: BraiinsClient) -> None:
    """Attach all Braiins resources to a FastMCP instance."""

    @mcp.resource("braiins://spot/settings")
    async def resource_spot_settings() -> str:
        """Current Braiins Hashpower spot market settings including
        price units (price_sat) and hashrate units (hr_unit)."""
        try:
            data = await _get_settings(client)
            return json.dumps(data)
        except BraiinsError as exc:
            return json.dumps({"error": exc.message, "status": exc.status_code})

    @mcp.resource("braiins://account/orders/open")
    async def resource_open_orders() -> str:
        """Snapshot of the tenant's currently open orders."""
        try:
            data = await _list_active_bids(client)
            return json.dumps(data)
        except BraiinsError as exc:
            return json.dumps({"error": exc.message, "status": exc.status_code})

    @mcp.resource("braiins://account/orders/history")
    async def resource_order_history() -> str:
        """Last 50 filled/canceled orders (paginated; first page)."""
        try:
            data = await _list_bids(client, limit=50, offset=0)
            return json.dumps(data)
        except BraiinsError as exc:
            return json.dumps({"error": exc.message, "status": exc.status_code})

    @mcp.resource("braiins://account/summary")
    async def resource_account_summary() -> str:
        """Account balance and exposure (not yet implemented)."""
        return json.dumps({
            "error": "Account summary endpoint not yet implemented in client layer.",
        })

    @mcp.resource("braiins://docs/error-codes")
    def resource_error_codes() -> str:
        """Normalized Braiins API error catalog."""
        return json.dumps(ERROR_CATALOG, indent=2)
