"""Tests for the MCP server layer (Phase 3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from braiins_hashpower_mcp.braiins.auth import BraiinsAuth
from braiins_hashpower_mcp.braiins.client import BraiinsClient
from braiins_hashpower_mcp.mcp.prompts import register_prompts
from braiins_hashpower_mcp.mcp.resources import register_resources
from braiins_hashpower_mcp.mcp.schemas import MCPToolResponse
from braiins_hashpower_mcp.mcp.tools import register_tools


@pytest.fixture
def mock_client() -> BraiinsClient:
    """Return a BraiinsClient whose underlying request is an AsyncMock."""
    auth = BraiinsAuth("test-key")
    client = BraiinsClient(auth, base_url="https://example.com/api/v1")
    client._client = AsyncMock(spec=httpx.AsyncClient)
    client._client.is_closed = False
    client._client.request = AsyncMock()
    return client


@pytest.fixture
def mcp_app(mock_client: BraiinsClient) -> FastMCP:
    """Return a fresh FastMCP instance with all components registered."""
    mcp = FastMCP("test_braiins")
    register_tools(mcp, mock_client)
    register_resources(mcp, mock_client)
    register_prompts(mcp)
    return mcp


def _parse_tool_response(result: Any) -> MCPToolResponse:
    """Unpack FastMCP call_tool result and parse the first text block."""
    content_blocks, _raw = result
    return MCPToolResponse.model_validate_json(content_blocks[0].text)


class TestRegistration:
    @pytest.mark.anyio
    async def test_tools_registered(self, mcp_app: FastMCP) -> None:
        tools = await mcp_app.list_tools()
        names = {t.name for t in tools}
        expected = {
            "get_market_settings",
            "get_orderbook",
            "list_orders",
            "get_deliveries",
            "create_bid",
            "cancel_order",
        }
        assert expected.issubset(names)

    @pytest.mark.anyio
    async def test_resources_registered(self, mcp_app: FastMCP) -> None:
        resources = await mcp_app.list_resources()
        uris = {str(r.uri) for r in resources}
        expected = {
            "braiins://spot/settings",
            "braiins://account/orders/open",
            "braiins://account/orders/history",
            "braiins://account/summary",
            "braiins://docs/error-codes",
        }
        assert expected.issubset(uris)

    @pytest.mark.anyio
    async def test_prompts_registered(self, mcp_app: FastMCP) -> None:
        prompts = await mcp_app.list_prompts()
        names = {p.name for p in prompts}
        expected = {
            "place_conservative_bid",
            "review_open_orders",
            "explain_price_units",
        }
        assert expected.issubset(names)


class TestTools:
    @pytest.mark.anyio
    async def test_get_market_settings_success(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(200, {"hr_unit": "EH/day"})
        parsed = _parse_tool_response(await mcp_app.call_tool("get_market_settings", {}))
        assert parsed.success is True
        assert parsed.data == {"hr_unit": "EH/day"}

    @pytest.mark.anyio
    async def test_get_orderbook_success(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(
            200, {"bids": [], "asks": []}
        )
        parsed = _parse_tool_response(
            await mcp_app.call_tool("get_orderbook", {"market": "spot", "depth": 10})
        )
        assert parsed.success is True
        assert parsed.data == {"bids": [], "asks": []}

    @pytest.mark.anyio
    async def test_list_orders_open(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(200, {"bids": [{"id": "B1"}]})
        parsed = _parse_tool_response(
            await mcp_app.call_tool(
                "list_orders", {"status": ["open"], "limit": 10, "offset": 0}
            )
        )
        assert parsed.success is True
        assert parsed.data == {"bids": [{"id": "B1"}]}

    @pytest.mark.anyio
    async def test_create_bid_dry_run(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        parsed = _parse_tool_response(
            await mcp_app.call_tool(
                "create_bid",
                {
                    "dest_upstream": "up1",
                    "amount_sat": 1000,
                    "price_sat": 50,
                    "client_order_id": "test-dry-123",
                    "dry_run": True,
                },
            )
        )
        assert parsed.success is True
        assert parsed.data is not None
        assert parsed.data["preview"] is True
        mock_client._client.request.assert_not_called()

    @pytest.mark.anyio
    async def test_create_bid_live(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(200, {"bid_id": "B999"})
        parsed = _parse_tool_response(
            await mcp_app.call_tool(
                "create_bid",
                {
                    "dest_upstream": "up1",
                    "amount_sat": 1000,
                    "price_sat": 50,
                    "client_order_id": "test-live-123",
                    "dry_run": False,
                },
            )
        )
        assert parsed.success is True
        assert parsed.data == {"bid_id": "B999"}

    @pytest.mark.anyio
    async def test_create_bid_idempotent(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(
            200, {"bid_id": "B999"}
        )
        parsed1 = _parse_tool_response(
            await mcp_app.call_tool(
                "create_bid",
                {
                    "dest_upstream": "up1",
                    "amount_sat": 1000,
                    "price_sat": 50,
                    "client_order_id": "idem-1",
                    "dry_run": False,
                },
            )
        )
        assert parsed1.success is True
        assert parsed1.data == {"bid_id": "B999"}

        parsed2 = _parse_tool_response(
            await mcp_app.call_tool(
                "create_bid",
                {
                    "dest_upstream": "up1",
                    "amount_sat": 1000,
                    "price_sat": 50,
                    "client_order_id": "idem-1",
                    "dry_run": False,
                },
            )
        )
        assert parsed2.success is True
        assert parsed2.data.get("duplicate") is True
        assert parsed2.data.get("cached_result") == {"bid_id": "B999"}
        assert mock_client._client.request.call_count == 1

    @pytest.mark.anyio
    async def test_cancel_order_success(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(204)
        parsed = _parse_tool_response(
            await mcp_app.call_tool(
                "cancel_order", {"order_id": "B123", "dry_run": False}
            )
        )
        assert parsed.success is True

    @pytest.mark.anyio
    async def test_cancel_order_missing_id(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        parsed = _parse_tool_response(await mcp_app.call_tool("cancel_order", {}))
        assert parsed.success is False
        assert "order_id" in (parsed.error or "").lower()

    @pytest.mark.anyio
    async def test_get_deliveries_not_implemented(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        parsed = _parse_tool_response(await mcp_app.call_tool("get_deliveries", {}))
        assert parsed.success is False
        assert "not yet implemented" in (parsed.error or "").lower()


class TestResources:
    @pytest.mark.anyio
    async def test_spot_settings_resource(
        self, mcp_app: FastMCP, mock_client: BraiinsClient
    ) -> None:
        mock_client._client.request.return_value = _mock_response(200, {"hr_unit": "PH/day"})
        contents = await mcp_app.read_resource("braiins://spot/settings")
        text = contents[0].content
        assert '{"hr_unit": "PH/day"}' in text

    @pytest.mark.anyio
    async def test_error_codes_resource(self, mcp_app: FastMCP) -> None:
        contents = await mcp_app.read_resource("braiins://docs/error-codes")
        text = contents[0].content
        assert "BraiinsValidationError" in text
        assert "BraiinsAuthError" in text


class TestPrompts:
    @pytest.mark.anyio
    async def test_place_conservative_bid_prompt(self, mcp_app: FastMCP) -> None:
        prompt = await mcp_app.get_prompt("place_conservative_bid")
        assert "conservative bid" in prompt.messages[0].content.text.lower()

    @pytest.mark.anyio
    async def test_review_open_orders_prompt(self, mcp_app: FastMCP) -> None:
        prompt = await mcp_app.get_prompt("review_open_orders")
        assert "open orders" in prompt.messages[0].content.text.lower()

    @pytest.mark.anyio
    async def test_explain_price_units_prompt(self, mcp_app: FastMCP) -> None:
        prompt = await mcp_app.get_prompt("explain_price_units")
        assert "price_sat" in prompt.messages[0].content.text


def _mock_response(status_code: int, json_data: dict[str, Any] | None = None) -> httpx.Response:
    """Build a minimal httpx.Response for mocking."""
    return httpx.Response(status_code, json=json_data)
