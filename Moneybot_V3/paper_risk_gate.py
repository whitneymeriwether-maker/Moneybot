"""Fail-closed, validation-only paper order risk gate.

This module does not submit, simulate, or record orders. Callers must
independently verify market-data authenticity and persist execution atomically.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone


@dataclass(frozen=True)
class RiskLimits:
    max_risk_fraction: Decimal = Decimal("0.015")
    max_daily_loss_fraction: Decimal = Decimal("0.03")
    max_exposure_fraction: Decimal = Decimal("0.50")
    max_drawdown_fraction: Decimal = Decimal("0.10")


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("Money must be a decimal string or Decimal")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid decimal") from None
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Invalid nonnegative cent amount")
    return amount


def validate_paper_order(*, equity, daily_loss, drawdown, current_exposure,
                         order_notional, order_risk, quote_verified,
                         quote_timestamp, now=None, limits=None):
    """Return (allowed, reason), never an executable order.

    All amounts are nonnegative USD. Exposure includes existing positions.
    A missing/stale/unverified quote, invalid input, or violated limit denies.
    """
    try:
        limits = limits or RiskLimits()
        if type(quote_verified) is not bool or not quote_verified:
            return False, "market data unverified"
        if not isinstance(quote_timestamp, datetime) or quote_timestamp.tzinfo is None:
            return False, "quote timestamp invalid"
        now = now or datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            return False, "clock invalid"
        age = (now - quote_timestamp).total_seconds()
        if not 0 <= age <= 60:
            return False, "quote stale or future-dated"
        equity, daily_loss, drawdown, current_exposure, order_notional, order_risk = [
            _money(x) for x in (equity, daily_loss, drawdown, current_exposure,
                                order_notional, order_risk)
        ]
        if equity <= 0 or order_notional <= 0 or order_risk <= 0:
            return False, "nonpositive equity or order"
        fractions = [limits.max_risk_fraction, limits.max_daily_loss_fraction,
                     limits.max_exposure_fraction, limits.max_drawdown_fraction]
        if any(type(x) is not Decimal or not x.is_finite() or not 0 < x < 1 for x in fractions):
            return False, "risk policy invalid"
        if daily_loss >= equity * limits.max_daily_loss_fraction:
            return False, "daily loss limit"
        if drawdown >= equity * limits.max_drawdown_fraction:
            return False, "drawdown limit"
        if order_risk > equity * limits.max_risk_fraction:
            return False, "per-order risk limit"
        if current_exposure + order_notional > equity * limits.max_exposure_fraction:
            return False, "exposure limit"
        return True, "validation only; no execution authorized"
    except (ValueError, TypeError, OverflowError, ArithmeticError):
        return False, "invalid risk input"
