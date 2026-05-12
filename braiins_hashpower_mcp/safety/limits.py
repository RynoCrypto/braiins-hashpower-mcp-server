"""Max notional, allowed markets."""

from __future__ import annotations

import os

from braiins_hashpower_mcp.braiins.errors import BraiinsError


class LimitError(BraiinsError):
    """Raised when an order exceeds configured spend limits."""


class SpendLimiter:
    """Enforce per-order spend caps in satoshi or USD notional."""

    def __init__(
        self,
        max_order_usd: float | None = None,
        max_order_sat: int | None = None,
        btc_usd_rate: float | None = None,
    ) -> None:
        self.max_order_usd = max_order_usd
        self.max_order_sat = max_order_sat
        self.btc_usd_rate = btc_usd_rate

        env_usd = os.getenv("BRAIINS_MAX_ORDER_USD")
        if self.max_order_usd is None and env_usd:
            self.max_order_usd = float(env_usd)
        env_sat = os.getenv("BRAIINS_MAX_ORDER_SAT")
        if self.max_order_sat is None and env_sat:
            self.max_order_sat = int(env_sat)
        env_rate = os.getenv("BRAIINS_BTC_USD_RATE")
        if self.btc_usd_rate is None and env_rate:
            self.btc_usd_rate = float(env_rate)

    def check_bid(self, amount_sat: int, price_sat: int | None = None) -> None:
        """Reject bid if it exceeds the configured spend cap.

        Args:
            amount_sat: Total bid amount in satoshi.
            price_sat: Optional price per unit in satoshi (ignored when
                amount_sat already represents total spend).

        Raises:
            LimitError: If the bid exceeds the cap.
        """
        if self.max_order_sat is not None and amount_sat > self.max_order_sat:
            raise LimitError(
                f"Bid amount {amount_sat} sat exceeds max_order_sat "
                f"limit of {self.max_order_sat}.",
                status_code=400,
            )

        if self.max_order_usd is not None:
            max_sat = self._usd_to_sat(self.max_order_usd)
            if amount_sat > max_sat:
                raise LimitError(
                    f"Bid amount {amount_sat} sat (~{self._sat_to_usd(amount_sat):.2f} USD) "
                    f"exceeds max_order_usd limit of {self.max_order_usd} USD.",
                    status_code=400,
                )

    def _usd_to_sat(self, usd: float) -> int:
        """Convert USD to satoshi using the cached BTC/USD rate."""
        if not self.btc_usd_rate or self.btc_usd_rate <= 0:
            fallback = 100_000.0
            return int(usd / fallback * 100_000_000)
        return int(usd / self.btc_usd_rate * 100_000_000)

    def _sat_to_usd(self, sat: int) -> float:
        """Convert satoshi to USD."""
        rate = self.btc_usd_rate or 100_000.0
        return sat * rate / 100_000_000
