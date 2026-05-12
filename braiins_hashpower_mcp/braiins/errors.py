"""Braiins API error mapping and exception hierarchy."""

from __future__ import annotations

from typing import Any


class BraiinsError(Exception):
    """Base exception for Braiins API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class BraiinsAuthError(BraiinsError):
    """Invalid or missing API token (401/403)."""


class BraiinsRateLimitError(BraiinsError):
    """Rate limit exceeded (429)."""


class BraiinsValidationError(BraiinsError):
    """Invalid request parameters (400)."""


class BraiinsNotFoundError(BraiinsError):
    """Resource not found (404)."""


class BraiinsServerError(BraiinsError):
    """Internal server error (5xx)."""


STATUS_TO_EXCEPTION: dict[int, type[BraiinsError]] = {
    400: BraiinsValidationError,
    401: BraiinsAuthError,
    403: BraiinsAuthError,
    404: BraiinsNotFoundError,
    429: BraiinsRateLimitError,
}


def raise_for_status(status_code: int, message: str, details: dict[str, Any] | None = None) -> None:
    """Raise the appropriate BraiinsError for an HTTP status code."""
    exc_cls = STATUS_TO_EXCEPTION.get(status_code, BraiinsServerError)
    raise exc_cls(message, status_code=status_code, details=details)
