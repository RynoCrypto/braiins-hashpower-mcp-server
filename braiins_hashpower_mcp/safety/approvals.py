"""Write-action gate flags."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from braiins_hashpower_mcp.braiins.errors import BraiinsError

logger = logging.getLogger(__name__)


class ApprovalError(BraiinsError):
    """Raised when a write action is blocked by the approval gate."""


class ApprovalGate:
    """Central gate for dry-run and read-only enforcement."""

    def __init__(
        self,
        mode: str | None = None,
        dry_run_default: bool = True,
    ) -> None:
        self.mode = (mode or os.getenv("BRAIINS_MODE") or "read_write").lower().strip()
        self.dry_run_default = dry_run_default
        if os.getenv("BRAIINS_DRY_RUN_DEFAULT", "").lower() in ("0", "false", "no"):
            self.dry_run_default = False

    def check_read_only(self, tool_name: str) -> None:
        """Block write operations when in read_only mode."""
        if self.mode == "read_only" and self.is_write_tool(tool_name):
            raise ApprovalError(
                f"Tool '{tool_name}' is blocked: server is in read_only mode.",
                status_code=403,
            )

    def gate_write(
        self,
        tool_name: str,
        params: dict[str, Any],
        dry_run: bool | None = None,
    ) -> dict[str, Any] | None:
        """Return a dry-run preview dict if dry_run is True, else None."""
        effective_dry_run = dry_run if dry_run is not None else self.dry_run_default
        if effective_dry_run:
            return {
                "preview": True,
                "tool": tool_name,
                "params": params,
                "note": "Dry-run preview; no live action taken.",
            }
        return None

    def log_attempt(
        self,
        tool_name: str,
        params: dict[str, Any],
        dry_run: bool,
        outcome: str,
    ) -> None:
        """Emit a structured JSON log line for every write attempt."""
        log_record = {
            "event": "write_attempt",
            "tool": tool_name,
            "dry_run": dry_run,
            "outcome": outcome,
            "params": _sanitize_params(params),
        }
        logger.info(json.dumps(log_record))

    @staticmethod
    def is_write_tool(tool_name: str) -> bool:
        """Return True if the named tool performs a write operation."""
        return tool_name in {"create_bid", "cancel_order", "edit_bid"}


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of params with secrets redacted."""
    safe = dict(params)
    for key in ("api_secret", "password", "token"):
        if key in safe:
            safe[key] = "***"
    return safe
