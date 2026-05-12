"""Pydantic schemas for MCP tools, resources, and prompts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MCPToolResponse(BaseModel):
    """Normalized response envelope returned by every MCP tool."""

    success: bool
    data: dict[str, Any] | list[Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    request_id: str | None = None
    raw_api_status: int | None = None


class GetOrderbookInput(BaseModel):
    """Input schema for get_orderbook tool."""

    market: Literal["spot"] = "spot"
    depth: int = Field(default=20, ge=1, le=100, description="Levels per side (not yet enforced)")


class ListOrdersInput(BaseModel):
    """Input schema for list_orders tool."""

    status: list[Literal["open", "filled", "canceled", "all"]] | None = Field(
        default=None,
        description="Filter by order status; maps to bid_status in API",
    )
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class GetDeliveriesInput(BaseModel):
    """Input schema for get_deliveries tool."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CreateBidInput(BaseModel):
    """Input schema for create_bid tool."""

    dest_upstream: str = Field(..., min_length=1, description="Destination upstream ID")
    amount_sat: int = Field(..., gt=0, description="Bid amount in satoshi")
    price_sat: int = Field(..., gt=0, description="Bid price in satoshi")
    market: Literal["spot"] = "spot"
    client_order_id: str | None = Field(
        default=None,
        description="Idempotency key; auto-generated if omitted",
    )
    dry_run: bool = Field(
        default=True,
        description="Preview only; no live order submitted when true",
    )


class CancelOrderInput(BaseModel):
    """Input schema for cancel_order tool."""

    order_id: str | None = Field(default=None, min_length=1)
    client_order_id: str | None = Field(default=None, min_length=1)
