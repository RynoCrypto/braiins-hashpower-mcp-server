"""TTL cache for /spot/settings."""

from __future__ import annotations

import time
from typing import Any

from .client import BraiinsClient


class SettingsCache:
    """In-memory TTL cache for Braiins spot market settings."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        """Initialize cache.

        Args:
            ttl_seconds: Time-to-live in seconds.
        """
        self._ttl = ttl_seconds
        self._data: dict[str, Any] | None = None
        self._expires_at: float = 0.0

    async def get(self, client: BraiinsClient) -> dict[str, Any]:
        """Return cached settings, refreshing if expired.

        Args:
            client: Braiins API client.

        Returns:
            Spot market settings dict.
        """
        now = time.monotonic()
        if self._data is not None and now < self._expires_at:
            return self._data

        self._data = await client.request("GET", "/spot/settings")
        self._expires_at = now + self._ttl
        return self._data

    def invalidate(self) -> None:
        """Force cache refresh on next access."""
        self._data = None
        self._expires_at = 0.0
