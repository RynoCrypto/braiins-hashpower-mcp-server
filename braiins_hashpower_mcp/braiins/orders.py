"""Order / bid CRUD operations."""

from __future__ import annotations

from typing import Any

from .client import BraiinsClient


async def list_bids(
    client: BraiinsClient,
    *,
    limit: int | None = None,
    offset: int | None = None,
    bid_status: str | None = None,
) -> dict[str, Any]:
    """List all bids (historical and active).

    Args:
        client: Braiins API client.
        limit: Pagination limit.
        offset: Pagination offset.
        bid_status: Filter by status (e.g. ``BID_STATUS_ACTIVE``).

    Returns:
        Paginated bids dict.
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if bid_status is not None:
        params["bid_status"] = bid_status
    return await client.request("GET", "/spot/bid", params=params)


async def list_active_bids(client: BraiinsClient) -> dict[str, Any]:
    """List active bids only.

    Args:
        client: Braiins API client.

    Returns:
        Active bids dict.
    """
    return await client.request("GET", "/spot/bid/current")


async def get_bid_detail(client: BraiinsClient, order_id: str) -> dict[str, Any]:
    """Get detailed bid information.

    Args:
        client: Braiins API client.
        order_id: Bid order ID (e.g. ``B123456789``).

    Returns:
        Bid detail dict.
    """
    return await client.request("GET", f"/spot/bid/detail/{order_id}")


async def create_bid(
    client: BraiinsClient,
    *,
    dest_upstream: str,
    amount_sat: int,
    price_sat: int,
    speed_limit_ph: int | None = None,
    cl_order_id: str | None = None,
    memo: str | None = None,
) -> dict[str, Any]:
    """Place a new bid (buy order).

    Args:
        client: Braiins API client.
        dest_upstream: Destination upstream ID.
        amount_sat: Bid amount in satoshi.
        price_sat: Bid price in satoshi.
        speed_limit_ph: Optional speed limit in PH.
        cl_order_id: Optional client-assigned order ID for idempotency.
        memo: Optional memo.

    Returns:
        Created bid dict.
    """
    body: dict[str, Any] = {
        "dest_upstream": dest_upstream,
        "amount_sat": amount_sat,
        "price_sat": price_sat,
    }
    if speed_limit_ph is not None:
        body["speed_limit_ph"] = speed_limit_ph
    if cl_order_id is not None:
        body["cl_order_id"] = cl_order_id
    if memo is not None:
        body["memo"] = memo
    return await client.request("POST", "/spot/bid", json=body)


async def edit_bid(
    client: BraiinsClient,
    *,
    bid_id: str | None = None,
    cl_order_id: str | None = None,
    new_amount_sat: int | None = None,
    new_price_sat: int | None = None,
    new_speed_limit_ph: int | None = None,
    memo: str | None = None,
) -> dict[str, Any]:
    """Edit an existing bid.

    Args:
        client: Braiins API client.
        bid_id: Braiins-assigned bid ID.
        cl_order_id: Client-assigned order ID (alternative to bid_id).
        new_amount_sat: New amount (must be greater than previous).
        new_price_sat: New price.
        new_speed_limit_ph: New speed limit (``0`` to disable).
        memo: Updated memo.

    Returns:
        Updated bid dict.
    """
    body: dict[str, Any] = {}
    if bid_id is not None:
        body["bid_id"] = bid_id
    if cl_order_id is not None:
        body["cl_order_id"] = cl_order_id
    if new_amount_sat is not None:
        body["new_amount_sat"] = new_amount_sat
    if new_price_sat is not None:
        body["new_price_sat"] = new_price_sat
    if new_speed_limit_ph is not None:
        body["new_speed_limit_ph"] = new_speed_limit_ph
    if memo is not None:
        body["memo"] = memo
    return await client.request("PUT", "/spot/bid", json=body)


async def cancel_bid(
    client: BraiinsClient,
    *,
    order_id: str | None = None,
    cl_order_id: str | None = None,
) -> dict[str, Any]:
    """Cancel a bid.

    Args:
        client: Braiins API client.
        order_id: Braiins-assigned order ID.
        cl_order_id: Client-assigned order ID.

    Returns:
        Empty dict or cancellation confirmation.
    """
    params: dict[str, Any] = {}
    if order_id is not None:
        params["order_id"] = order_id
    if cl_order_id is not None:
        params["cl_order_id"] = cl_order_id
    return await client.request("DELETE", "/spot/bid", params=params)
