"""Integration tests for MCP tools with mocked Braiins client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from braiins_hashpower_mcp.braiins.errors import BraiinsError
from braiins_hashpower_mcp.braiins.market import (
    get_fee,
    get_orderbook,
    get_settings,
    get_trades,
)
from braiins_hashpower_mcp.braiins.orders import (
    cancel_bid,
    create_bid,
    list_active_bids,
    list_bids,
)


class TestToolsIntegration:
    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        client.request = AsyncMock()
        return client

    @pytest.mark.anyio
    async def test_get_settings_returns_dict(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {"hr_unit": "EH/day"}
        result = await get_settings(mock_client)
        assert result["hr_unit"] == "EH/day"

    @pytest.mark.anyio
    async def test_get_trades_with_limit(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {"trades": [{"id": "t1"}]}
        result = await get_trades(mock_client, limit=5)
        assert len(result["trades"]) == 1

    @pytest.mark.anyio
    async def test_get_fee(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {"fee": 0.01}
        result = await get_fee(mock_client)
        assert result["fee"] == 0.01

    @pytest.mark.anyio
    async def test_get_orderbook(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {"bids": [], "asks": []}
        result = await get_orderbook(mock_client)
        assert result["bids"] == []

    @pytest.mark.anyio
    async def test_list_bids_propagates_error(self, mock_client: MagicMock) -> None:
        mock_client.request.side_effect = BraiinsError("API down", status_code=503)
        with pytest.raises(BraiinsError) as exc_info:
            await list_bids(mock_client)
        assert exc_info.value.status_code == 503

    @pytest.mark.anyio
    async def test_list_active_bids(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {"bids": [{"id": "b1"}]}
        result = await list_active_bids(mock_client)
        assert result["bids"][0]["id"] == "b1"

    @pytest.mark.anyio
    async def test_create_bid_propagates_error(self, mock_client: MagicMock) -> None:
        mock_client.request.side_effect = BraiinsError("insufficient funds", status_code=400)
        with pytest.raises(BraiinsError) as exc_info:
            await create_bid(
                mock_client,
                dest_upstream="up1",
                amount_sat=1000,
                price_sat=50,
                cl_order_id="cid-1",
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.anyio
    async def test_cancel_bid(self, mock_client: MagicMock) -> None:
        mock_client.request.return_value = {}
        result = await cancel_bid(mock_client, order_id="B123")
        assert result == {}
