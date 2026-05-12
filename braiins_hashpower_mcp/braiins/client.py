"""Async HTTP client for the Braiins Hashpower API."""

from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .auth import BraiinsAuth
from .errors import raise_for_status

DEFAULT_BASE_URL = "https://hashpower.braiins.com/api/v1"


class BraiinsClient:
    """Async client for the Braiins Hashpower spot-market REST API."""

    def __init__(
        self,
        auth: BraiinsAuth,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            auth: Authentication handler.
            base_url: Braiins API base URL. Defaults to ``DEFAULT_BASE_URL``
                or the ``BRAIINS_API_BASE_URL`` environment variable.
            timeout: Request timeout in seconds.
        """
        self.auth = auth
        base = base_url or os.getenv("BRAIINS_API_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = base.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.auth.headers(),
                timeout=self.timeout,
            )
        return self._client

    @retry(
        retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Braiins API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API path (e.g. ``/spot/settings``).
            params: Query parameters.
            json: JSON request body.

        Returns:
            Parsed JSON response.

        Raises:
            BraiinsError: On API errors (4xx/5xx).
        """
        client = await self._get_client()
        response = await client.request(method, path, params=params, json=json)

        if response.status_code >= 400:
            detail = self._extract_error(response)
            raise_for_status(
                response.status_code,
                detail["message"],
                details=detail.get("details"),
            )

        if response.status_code == 204:
            return {}

        return dict(response.json())

    @staticmethod
    def _extract_error(response: httpx.Response) -> dict[str, Any]:
        """Extract error message from response body or headers."""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error") or str(payload)
                return {"message": message, "details": payload}
        except (ValueError, TypeError):
            pass

        # Fallback to grpc-message header (URL-encoded per Braiins docs)
        grpc_msg = response.headers.get("grpc-message")
        if grpc_msg:
            import urllib.parse
            return {"message": urllib.parse.unquote(grpc_msg)}

        return {"message": f"HTTP {response.status_code}"}

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> BraiinsClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
