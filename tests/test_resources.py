"""Integration tests for MCP resources and cache behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from braiins_hashpower_mcp.braiins.errors import BraiinsError
from braiins_hashpower_mcp.braiins.settings_cache import SettingsCache


class TestSettingsCache:
    @pytest.mark.anyio
    async def test_cold_cache_fetches(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(return_value={"hr_unit": "EH/day"})
        cache = SettingsCache(ttl_seconds=60.0)
        result = await cache.get(client)
        assert result == {"hr_unit": "EH/day"}
        client.request.assert_awaited_once()

    @pytest.mark.anyio
    async def test_warm_cache_skips_fetch(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(return_value={"hr_unit": "EH/day"})
        cache = SettingsCache(ttl_seconds=60.0)
        await cache.get(client)
        await cache.get(client)
        assert client.request.call_count == 1

    @pytest.mark.anyio
    async def test_ttl_expiration_refetches(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(return_value={"hr_unit": "EH/day"})
        cache = SettingsCache(ttl_seconds=0.0)
        await cache.get(client)
        await cache.get(client)
        assert client.request.call_count == 2

    @pytest.mark.anyio
    async def test_invalidate_clears_cache(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(return_value={"hr_unit": "EH/day"})
        cache = SettingsCache(ttl_seconds=60.0)
        await cache.get(client)
        cache.invalidate()
        await cache.get(client)
        assert client.request.call_count == 2

    @pytest.mark.anyio
    async def test_error_on_fetch_propagates(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(side_effect=BraiinsError("timeout", status_code=504))
        cache = SettingsCache(ttl_seconds=60.0)
        with pytest.raises(BraiinsError) as exc_info:
            await cache.get(client)
        assert exc_info.value.status_code == 504
