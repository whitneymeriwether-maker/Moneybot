"""Safety regression tests for the inert V3 risk validator."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_risk_gate import validate_paper_order


NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)


def check(**changes):
    params = dict(equity="10000.00", daily_loss="0.00", drawdown="0.00",
                  current_exposure="1000.00", order_notional="100.00",
                  order_risk="50.00", quote_verified=True, quote_timestamp=NOW,
                  now=NOW)
    params.update(changes)
    return validate_paper_order(**params)


def test_valid_order_is_validation_only():
    assert check() == (True, "validation only; no execution authorized")


def test_quote_must_be_verified_recent_and_not_future():
    assert not check(quote_verified=False)[0]
    assert not check(quote_timestamp=NOW - timedelta(seconds=61))[0]
    assert not check(quote_timestamp=NOW + timedelta(seconds=1))[0]
    assert not check(quote_timestamp=NOW.replace(tzinfo=None))[0]


def test_limits_fail_closed_at_boundaries():
    assert not check(daily_loss="300.00")[0]
    assert not check(drawdown="1000.00")[0]
    assert not check(order_risk="150.01")[0]
    assert not check(current_exposure="4900.00", order_notional="100.01")[0]
    assert check(order_risk="150.00", order_notional="200.00", current_exposure="4800.00")[0]


def test_invalid_inputs_fail_closed():
    for invalid in ("NaN", "Infinity", "-1.00", "0.001", "", "not money"):
        assert not check(order_notional=invalid)[0]
    assert not check(equity="0.00")[0]
    assert not check(order_risk="0.00")[0]
    assert not check(quote_verified=1)[0]
    assert not check(equity=10000.0)[0]


def test_risk_cannot_exceed_order_notional():
    assert not check(order_notional="10.00", order_risk="10.01")[0]
    assert check(order_notional="100.00", order_risk="100.00")[0]
