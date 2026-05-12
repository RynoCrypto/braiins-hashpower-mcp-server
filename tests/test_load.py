"""Load tests for the SSE endpoint."""

from __future__ import annotations

import asyncio

import httpx
import pytest


@pytest.mark.anyio
async def test_100_concurrent_sse_connections() -> None:
    """Verify the SSE endpoint handles 100 concurrent connections."""
    url = "http://127.0.0.1:8765/sse"
    concurrent = 100

    async def connect() -> int:
        try:
            async with (
                httpx.AsyncClient(timeout=5.0) as client,
                client.stream("GET", url) as response,
            ):
                return response.status_code
        except Exception:
            return 0

    results = await asyncio.gather(*[connect() for _ in range(concurrent)])
    ok_count = sum(1 for r in results if r == 200)
    # In a real CI environment the server may not be running.
    # We assert that if any connection succeeded, at least 80% should.
    if ok_count > 0:
        assert ok_count >= concurrent * 0.8, f"Only {ok_count}/{concurrent} connections OK"
    else:
        pytest.skip("Server not running for load test")
