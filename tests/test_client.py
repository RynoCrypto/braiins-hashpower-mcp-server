"""Tests for Braiins API client layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from braiins_hashpower_mcp.braiins.auth import BraiinsAuth
from braiins_hashpower_mcp.braiins.client import BraiinsClient
from braiins_hashpower_mcp.braiins.errors import (
    BraiinsAuthError,
    BraiinsRateLimitError,
    BraiinsServerError,
    BraiinsValidationError,
)
from braiins_hashpower_mcp.braiins.market import get_orderbook, get_settings, get_stats
from braiins_hashpower_mcp.braiins.orders import cancel_bid, create_bid, list_active_bids
from braiins_hashpower_mcp.braiins.settings_cache import SettingsCache


@pytest.fixture
def auth() -> BraiinsAuth:
    return BraiinsAuth("test-api-key")


@pytest.fixture
def client(auth: BraiinsAuth) -> BraiinsClient:
    return BraiinsClient(auth, base_url="https://example.com/api/v1")


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict | None = None,
) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = Exception("No JSON body")
    response.headers = httpx.Headers(headers or {})
    return response


class TestAuth:
    def test_headers(self) -> None:
        auth = BraiinsAuth("secret123")
        headers = auth.headers()
        assert headers["apikey"] == "secret123"
        assert headers["Content-Type"] == "application/json"


class TestClient:
    @pytest.mark.anyio
    async def test_get_request_success(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"unit": "EH/day"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await client.request("GET", "/spot/settings")
            assert result == {"unit": "EH/day"}

    @pytest.mark.anyio
    async def test_post_request_success(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"bid_id": "B123"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await client.request("POST", "/spot/bid", json={"amount_sat": 1000})
            assert result == {"bid_id": "B123"}

    @pytest.mark.anyio
    async def test_401_raises_auth_error(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(401, {"error": "unauthorized"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(BraiinsAuthError):
                await client.request("GET", "/account/balance")

    @pytest.mark.anyio
    async def test_400_raises_validation_error(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(400, {"message": "bad request"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(BraiinsValidationError):
                await client.request("POST", "/spot/bid", json={})

    @pytest.mark.anyio
    async def test_429_raises_rate_limit(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(429)
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(BraiinsRateLimitError):
                await client.request("GET", "/spot/orderbook")

    @pytest.mark.anyio
    async def test_500_raises_server_error(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(500, {"message": "internal"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(BraiinsServerError):
                await client.request("GET", "/spot/settings")

    @pytest.mark.anyio
    async def test_grpc_message_header_parsing(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(400, headers={"grpc-message": "Bid%20too%20low"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(BraiinsValidationError) as exc_info:
                await client.request("POST", "/spot/bid")
            assert "Bid too low" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_context_manager(self, auth: BraiinsAuth) -> None:
        client = BraiinsClient(auth, base_url="https://example.com")
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.aclose = AsyncMock()
            mock_get_client.return_value = mock_http

            async with client as c:
                assert c is client


class TestMarket:
    @pytest.mark.anyio
    async def test_get_settings(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"hr_unit": "EH/day"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await get_settings(client)
            assert result["hr_unit"] == "EH/day"

    @pytest.mark.anyio
    async def test_get_orderbook(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"bids": [], "asks": []})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await get_orderbook(client)
            assert result["bids"] == []

    @pytest.mark.anyio
    async def test_get_stats(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"volume_24h": 100})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await get_stats(client)
            assert result["volume_24h"] == 100


class TestOrders:
    @pytest.mark.anyio
    async def test_list_active_bids(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"bids": []})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await list_active_bids(client)
            assert result["bids"] == []

    @pytest.mark.anyio
    async def test_create_bid(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"bid_id": "B999"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await create_bid(
                client,
                dest_upstream="upstream1",
                amount_sat=5000,
                price_sat=100,
                cl_order_id="my-order-1",
            )
            assert result["bid_id"] == "B999"

    @pytest.mark.anyio
    async def test_cancel_bid(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(204)
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await cancel_bid(client, order_id="B123")
            assert result == {}


class TestSettingsCache:
    @pytest.mark.anyio
    async def test_cache_hit(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"hr_unit": "EH/day"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            cache = SettingsCache(ttl_seconds=60.0)
            result1 = await cache.get(client)
            result2 = await cache.get(client)
            assert result1 == result2 == {"hr_unit": "EH/day"}
            # Should only call API once
            assert mock_http.request.call_count == 1

    @pytest.mark.anyio
    async def test_cache_invalidate(self, client: BraiinsClient) -> None:
        mock_resp = _mock_response(200, {"hr_unit": "EH/day"})
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            cache = SettingsCache(ttl_seconds=60.0)
            await cache.get(client)
            cache.invalidate()
            await cache.get(client)
            assert mock_http.request.call_count == 2
