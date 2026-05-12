"""Tests for safety layer."""

from __future__ import annotations

import json
import logging

import pytest

from braiins_hashpower_mcp.safety import (
    ApprovalError,
    ApprovalGate,
    IdempotencyStore,
    LimitError,
    SpendLimiter,
    UnitValidator,
    ValidationError,
)


class TestApprovalGate:
    def test_default_mode_is_read_write(self) -> None:
        gate = ApprovalGate(mode=None)
        assert gate.mode == "read_write"

    def test_read_only_blocks_writes(self) -> None:
        gate = ApprovalGate(mode="read_only")
        with pytest.raises(ApprovalError) as exc_info:
            gate.check_read_only("create_bid")
        assert "read_only" in str(exc_info.value)
        assert exc_info.value.status_code == 403

    def test_read_only_allows_reads(self) -> None:
        gate = ApprovalGate(mode="read_only")
        gate.check_read_only("get_market_settings")

    def test_dry_run_default_true(self) -> None:
        gate = ApprovalGate()
        preview = gate.gate_write("create_bid", {"amount_sat": 100}, dry_run=True)
        assert preview is not None
        assert preview["preview"] is True

    def test_dry_run_false_allows_through(self) -> None:
        gate = ApprovalGate()
        preview = gate.gate_write("create_bid", {"amount_sat": 100}, dry_run=False)
        assert preview is None

    def test_dry_run_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRAIINS_DRY_RUN_DEFAULT", "false")
        gate = ApprovalGate()
        assert gate.dry_run_default is False

    def test_log_attempt_emits_structured_json(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gate = ApprovalGate()
        with caplog.at_level(
            logging.INFO, logger="braiins_hashpower_mcp.safety.approvals"
        ):
            gate.log_attempt("create_bid", {"amount_sat": 100}, True, "dry_run_preview")
        assert len(caplog.records) == 1
        record = json.loads(caplog.records[0].message)
        assert record["event"] == "write_attempt"
        assert record["tool"] == "create_bid"
        assert record["dry_run"] is True
        assert record["outcome"] == "dry_run_preview"

    def test_log_attempt_redacts_secrets(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gate = ApprovalGate()
        with caplog.at_level(
            logging.INFO, logger="braiins_hashpower_mcp.safety.approvals"
        ):
            gate.log_attempt("create_bid", {"api_secret": "shh"}, True, "preview")
        record = json.loads(caplog.records[0].message)
        assert record["params"]["api_secret"] == "***"


class TestSpendLimiter:
    def test_no_limits_allows_anything(self) -> None:
        limiter = SpendLimiter()
        limiter.check_bid(1_000_000_000)

    def test_max_order_sat_enforced(self) -> None:
        limiter = SpendLimiter(max_order_sat=5000)
        limiter.check_bid(4000)
        with pytest.raises(LimitError) as exc_info:
            limiter.check_bid(5001)
        assert "5001" in exc_info.value.message
        assert "5000" in exc_info.value.message

    def test_max_order_usd_enforced(self) -> None:
        limiter = SpendLimiter(max_order_usd=100, btc_usd_rate=100_000)
        limiter.check_bid(99_999)
        with pytest.raises(LimitError) as exc_info:
            limiter.check_bid(100_001)
        assert "USD" in exc_info.value.message

    def test_env_var_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRAIINS_MAX_ORDER_SAT", "1000")
        limiter = SpendLimiter()
        with pytest.raises(LimitError):
            limiter.check_bid(1001)

    def test_fallback_rate_when_btc_usd_rate_missing(self) -> None:
        limiter = SpendLimiter(max_order_usd=1_000_000)
        limiter.check_bid(1_000_000_000)
        with pytest.raises(LimitError):
            limiter.check_bid(1_000_000_001)


class TestUnitValidator:
    def test_valid_bid_passes(self) -> None:
        validator = UnitValidator()
        validator.validate_bid("upstream-1", 1000, 50)

    def test_invalid_upstream_rejected(self) -> None:
        validator = UnitValidator()
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_bid("upstream 1", 1000, 50)
        assert "dest_upstream" in exc_info.value.message

    def test_non_positive_amount_rejected(self) -> None:
        validator = UnitValidator()
        with pytest.raises(ValidationError):
            validator.validate_bid("up1", 0, 50)

    def test_non_positive_price_rejected(self) -> None:
        validator = UnitValidator()
        with pytest.raises(ValidationError):
            validator.validate_bid("up1", 1000, 0)

    def test_settings_bounds_enforced(self) -> None:
        validator = UnitValidator()
        settings = {
            "min_amount_sat": 100,
            "max_amount_sat": 1000,
            "min_price_sat": 10,
            "max_price_sat": 100,
        }
        validator.validate_bid("up1", 500, 50, settings=settings)
        with pytest.raises(ValidationError) as exc_info:
            validator.validate_bid("up1", 50, 50, settings=settings)
        assert "below market minimum" in exc_info.value.message

    def test_cancel_without_id_rejected(self) -> None:
        validator = UnitValidator()
        with pytest.raises(ValidationError):
            validator.validate_cancel(None, None)

    def test_cancel_with_order_id_passes(self) -> None:
        validator = UnitValidator()
        validator.validate_cancel("B123", None)


class TestIdempotencyStore:
    def test_none_key_is_always_new(self) -> None:
        store = IdempotencyStore()
        is_new, cached = store.check(None)
        assert is_new is True
        assert cached is None

    def test_new_key_is_new(self) -> None:
        store = IdempotencyStore()
        is_new, cached = store.check("key-1")
        assert is_new is True
        assert cached is None

    def test_duplicate_key_returns_cached_result(self) -> None:
        store = IdempotencyStore()
        store.store("key-1", {"result": "ok"})
        is_new, cached = store.check("key-1")
        assert is_new is False
        assert cached == {"result": "ok"}

    def test_eviction_on_max_size(self) -> None:
        store = IdempotencyStore(max_size=4)
        for i in range(5):
            store.store(f"k{i}", i)
        is_new, _ = store.check("k0")
        assert is_new is True
        is_new, _ = store.check("k4")
        assert is_new is False
