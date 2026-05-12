"""API key authentication for Braiins requests.

The Braiins Hashpower spot-market API uses a simple ``apikey`` header.
No HMAC signing is required for this API.
"""

from __future__ import annotations


class BraiinsAuth:
    """Holds API credentials and produces request headers."""

    def __init__(self, api_key: str) -> None:
        """Initialize with a Braiins API token.

        Args:
            api_key: The Braiins API token (owner or read-only).
        """
        self.api_key = api_key

    def headers(self) -> dict[str, str]:
        """Return headers to include with every API request."""
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
