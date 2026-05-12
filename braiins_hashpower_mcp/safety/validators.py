"""Unit normalization and pre-flight checks."""

from __future__ import annotations

import re
from typing import Any

from braiins_hashpower_mcp.braiins.errors import BraiinsError


class ValidationError(BraiinsError):
    """Raised when input fails pre-flight validation."""


class UnitValidator:
    """Validate tool inputs against market settings and basic rules."""

    _UPSTREAM_RE = re.compile(r"^[A-Za-z0-9._-]+$")

    def validate_bid(
        self,
        dest_upstream: str,
        amount_sat: int,
        price_sat: int,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Validate create_bid parameters.

        Args:
            dest_upstream: Destination upstream ID.
            amount_sat: Bid amount in satoshi.
            price_sat: Bid price in satoshi.
            settings: Optional market settings for bound checking.

        Raises:
            ValidationError: On any validation failure.
        """
        if not dest_upstream or not self._UPSTREAM_RE.match(dest_upstream):
            raise ValidationError(
                f"Invalid dest_upstream '{dest_upstream}'; must match "
                "alphanumeric/hyphen/dot/underscore pattern.",
                status_code=400,
            )
        if amount_sat <= 0:
            raise ValidationError(
                "amount_sat must be positive.",
                status_code=400,
            )
        if price_sat <= 0:
            raise ValidationError(
                "price_sat must be positive.",
                status_code=400,
            )

        if settings:
            min_amount = settings.get("min_amount_sat")
            max_amount = settings.get("max_amount_sat")
            min_price = settings.get("min_price_sat")
            max_price = settings.get("max_price_sat")
            if min_amount is not None and amount_sat < min_amount:
                raise ValidationError(
                    f"amount_sat {amount_sat} below market minimum {min_amount}.",
                    status_code=400,
                )
            if max_amount is not None and amount_sat > max_amount:
                raise ValidationError(
                    f"amount_sat {amount_sat} above market maximum {max_amount}.",
                    status_code=400,
                )
            if min_price is not None and price_sat < min_price:
                raise ValidationError(
                    f"price_sat {price_sat} below market minimum {min_price}.",
                    status_code=400,
                )
            if max_price is not None and price_sat > max_price:
                raise ValidationError(
                    f"price_sat {price_sat} above market maximum {max_price}.",
                    status_code=400,
                )

    def validate_cancel(
        self,
        order_id: str | None,
        client_order_id: str | None,
    ) -> None:
        """Validate cancel_order parameters.

        Raises:
            ValidationError: If neither ID is provided.
        """
        if not order_id and not client_order_id:
            raise ValidationError(
                "Either order_id or client_order_id must be provided.",
                status_code=400,
            )


class IdempotencyStore:
    """In-memory store for recent idempotency keys and their results."""

    def __init__(self, max_size: int = 10_000) -> None:
        self._results: dict[str, Any] = {}
        self._max_size = max_size

    def check(self, key: str | None) -> tuple[bool, Any]:
        """Return (is_new, cached_result). None keys are always new."""
        if key is None:
            return True, None
        if key in self._results:
            return False, self._results[key]
        return True, None

    def store(self, key: str | None, result: Any) -> None:
        """Store a result for an idempotency key. None keys are ignored."""
        if key is None:
            return
        self._results[key] = result
        if len(self._results) > self._max_size:
            items = list(self._results.items())
            self._results = dict(items[len(items) // 2 :])
