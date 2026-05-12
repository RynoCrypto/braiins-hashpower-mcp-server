"""Tests for FastMCP server lifecycle and health endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from braiins_hashpower_mcp.server import (
    _health_handler,
    _ready_handler,
    lifespan,
    mcp,
    state,
)


class TestAppHealth:
    def test_health_endpoint(self) -> None:
        app = mcp.sse_app()
        app.add_route("/health", _health_handler)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    def test_ready_without_client(self) -> None:
        original = state.client
        state.client = None
        try:
            app = mcp.sse_app()
            app.add_route("/ready", _ready_handler)
            with TestClient(app) as client:
                resp = client.get("/ready")
                assert resp.status_code == 503
                assert resp.json()["status"] == "not_ready"
        finally:
            state.client = original

    def test_ready_with_client(self) -> None:
        original = state.client
        state.client = MagicMock()
        try:
            app = mcp.sse_app()
            app.add_route("/ready", _ready_handler)
            with TestClient(app) as client:
                resp = client.get("/ready")
                assert resp.status_code == 200
                assert resp.json()["status"] == "ready"
        finally:
            state.client = original


class TestLifespan:
    @pytest.mark.anyio
    async def test_lifespan_enter_exit(self) -> None:
        with patch("braiins_hashpower_mcp.server.register_tools") as mock_tools, \
             patch("braiins_hashpower_mcp.server.register_resources") as mock_resources, \
             patch("braiins_hashpower_mcp.server.register_prompts") as mock_prompts:
            ctx = lifespan(mcp)
            await ctx.__aenter__()
            assert state.client is not None
            mock_tools.assert_called_once()
            mock_resources.assert_called_once()
            mock_prompts.assert_called_once()
            await ctx.__aexit__(None, None, None)


class TestMain:
    def test_main_runs_uvicorn(self) -> None:
        with patch("uvicorn.run") as mock_run:
            from braiins_hashpower_mcp.server import main
            main()
            assert mock_run.called
