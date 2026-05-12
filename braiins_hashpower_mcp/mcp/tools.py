"""MCP tools exposing the Braiins Hashpower API."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from braiins_hashpower_mcp.braiins.client import BraiinsClient
from braiins_hashpower_mcp.braiins.errors import BraiinsError
from braiins_hashpower_mcp.braiins.market import (
    get_orderbook as _get_orderbook,
)
from braiins_hashpower_mcp.braiins.market import (
    get_settings as _get_settings,
)
from braiins_hashpower_mcp.braiins.orders import (
    cancel_bid as _cancel_bid,
)
from braiins_hashpower_mcp.braiins.orders import (
    create_bid as _create_bid,
)
from braiins_hashpower_mcp.braiins.orders import (
    list_active_bids as _list_active_bids,
)
from braiins_hashpower_mcp.braiins.orders import (
    list_bids as _list_bids,
)
from braiins_hashpower_mcp.mcp.schemas import MCPToolResponse

logger = logging.getLogger(__name__)


def _make_request_id() -> str:
    return str(uuid.uuid4())[:8]


def _success(data: Any, request_id: str) -> MCPToolResponse:
    return MCPToolResponse(success=True, data=data, request_id=request_id)


def _error(exc: BraiinsError, request_id: str) -> MCPToolResponse:
    return MCPToolResponse(
        success=False,
        error=exc.message,
        raw_api_status=exc.status_code,
        request_id=request_id,
    )


def register_tools(mcp: FastMCP, client: BraiinsClient) -> None:
    """Attach all Braiins tools to a FastMCP instance."""

    @mcp.tool()
    async def get_market_settings() -> MCPToolResponse:
        """Fetch current Braiins Hashpower spot market settings.

        Returns price unit (price_sat), hashrate unit (hr_unit), and
        min/max order bounds. Always call this before placing a bid to
        ensure correct unit interpretation.
        """
        req_id = _make_request_id()
        try:
            data = await _get_settings(client)
            return _success(data, req_id)
        except BraiinsError as exc:
            return _error(exc, req_id)

    @mcp.tool()
    async def get_orderbook(
        market: Literal["spot"] = "spot",
        depth: int = 20,
    ) -> MCPToolResponse:
        """Return bid/ask depth for the Braiins Hashpower spot market.

        Prices are in units from /spot/settings. Always call
        get_market_settings first to interpret values correctly.
        """
        req_id = _make_request_id()
        try:
            data = await _get_orderbook(client)
            return _success(data, req_id)
        except BraiinsError as exc:
            return _error(exc, req_id)

    @mcp.tool()
    async def list_orders(
        status: list[Literal["open", "filled", "canceled", "all"]] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> MCPToolResponse:
        """Return a paginated list of the authenticated tenant's orders.

        Defaults to all statuses if status is not specified.
        """
        req_id = _make_request_id()
        try:
            status_filter = status or ["all"]
            if "open" in status_filter and len(status_filter) == 1:
                data = await _list_active_bids(client)
            else:
                bid_status = None
                if status_filter and "all" not in status_filter:
                    bid_status = ",".join(status_filter)
                data = await _list_bids(
                    client,
                    limit=limit,
                    offset=offset,
                    bid_status=bid_status,
                )
            return _success(data, req_id)
        except BraiinsError as exc:
            return _error(exc, req_id)

    @mcp.tool()
    async def get_deliveries(
        limit: int = 20,
        offset: int = 0,
    ) -> MCPToolResponse:
        """Return hashrate delivery records and allocation state.

        Useful for verifying that purchased hashrate has been allocated
        and is delivering as expected.
        """
        req_id = _make_request_id()
        return MCPToolResponse(
            success=False,
            error="Deliveries endpoint not yet implemented in client layer.",
            request_id=req_id,
        )

    @mcp.tool()
    async def create_bid(
        dest_upstream: str,
        amount_sat: int,
        price_sat: int,
        market: Literal["spot"] = "spot",
        client_order_id: str | None = None,
        dry_run: bool = True,
    ) -> MCPToolResponse:
        """Place a bid on the Braiins Hashpower spot market.

        IMPORTANT: Price and amount are in satoshi units.
        Always call get_market_settings first to verify units before
        composing inputs.

        dry_run=true (default) validates and returns a preview without
        submitting to the API. Set dry_run=false to place a live order.
        """
        req_id = _make_request_id()
        if dry_run:
            return _success(
                {
                    "preview": True,
                    "dest_upstream": dest_upstream,
                    "amount_sat": amount_sat,
                    "price_sat": price_sat,
                    "market": market,
                    "client_order_id": client_order_id,
                    "note": "Dry-run preview; no live order submitted.",
                },
                req_id,
            )
        try:
            data = await _create_bid(
                client,
                dest_upstream=dest_upstream,
                amount_sat=amount_sat,
                price_sat=price_sat,
                cl_order_id=client_order_id,
            )
            return _success(data, req_id)
        except BraiinsError as exc:
            return _error(exc, req_id)

    @mcp.tool()
    async def cancel_order(
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> MCPToolResponse:
        """Cancel an open order on the Braiins Hashpower spot market.

        Use list_orders to retrieve valid order IDs.
        """
        req_id = _make_request_id()
        if not order_id and not client_order_id:
            return MCPToolResponse(
                success=False,
                error="Either order_id or client_order_id must be provided.",
                request_id=req_id,
            )
        try:
            data = await _cancel_bid(
                client,
                order_id=order_id,
                cl_order_id=client_order_id,
            )
            return _success(data, req_id)
        except BraiinsError as exc:
            return _error(exc, req_id)
