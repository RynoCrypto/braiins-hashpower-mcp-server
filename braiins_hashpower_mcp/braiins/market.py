"""Orderbook and market data wrappers."""

from __future__ import annotations

from typing import Any

from .client import BraiinsClient


async def get_settings(client: BraiinsClient) -> dict[str, Any]:
    """Fetch spot market settings.

    Args:
        client: Braiins API client.

    Returns:
        Market configuration dict.
    """
    return await client.request("GET", "/spot/settings")


async def get_orderbook(client: BraiinsClient) -> dict[str, Any]:
    """Fetch current orderbook snapshot.

    Args:
        client: Braiins API client.

    Returns:
        Orderbook dict with bids/asks.
    """
    return await client.request("GET", "/spot/orderbook")


async def get_trades(
    client: BraiinsClient,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch recent trade history.

    Args:
        client: Braiins API client.
        limit: Maximum number of trades to return.

    Returns:
        Trades list dict.
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    return await client.request("GET", "/spot/trades", params=params)


async def get_stats(client: BraiinsClient) -> dict[str, Any]:
    """Fetch market statistics.

    Args:
        client: Braiins API client.

    Returns:
        Stats dict (volume, best bid/ask, etc.).
    """
    return await client.request("GET", "/spot/stats")


async def get_fee(client: BraiinsClient) -> dict[str, Any]:
    """Fetch current fee structure.

    Args:
        client: Braiins API client.

    Returns:
        Fee structure dict.
    """
    return await client.request("GET", "/spot/fee")
