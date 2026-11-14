"""Fail-closed validation for authenticated market-data observations.

Provider transport must authenticate using its own credentials/TLS before
calling this module. Validation alone is not authentication or authorization
to submit orders. All times are UTC-aware; quotes are not executable fills.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")
_ALLOWED = frozenset({"polygon", "alpaca", "massive"})


def verified_quote(payload, *, provider, authenticated, expected_symbol,
                   now=None, max_age_seconds=90):
    """Return a normalized research quote or raise ValueError (no fallback).

    The caller must have independently verified provider identity, successful
    authenticated HTTPS response, and correct instrument mapping. A quote
    cannot authorize trading without separate risk and ledger gates.
    """
    if type(authenticated) is not bool or not authenticated:
        raise ValueError("Market data provider not authenticated")
    if provider not in _ALLOWED or type(provider) is not str:
        raise ValueError("Unknown market data provider")
    if type(expected_symbol) is not str or not _SYMBOL.fullmatch(expected_symbol):
        raise ValueError("Invalid expected symbol")
    if type(payload) is not dict or set(payload) != {"symbol", "timestamp", "price"}:
        raise ValueError("Invalid quote fields")
    if payload["symbol"] != expected_symbol:
        raise ValueError("Market symbol mismatch")
    if type(payload["timestamp"]) is not datetime:
        raise ValueError("Market timestamp must be datetime")
    observed = payload["timestamp"]
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("Market timestamp must be timezone-aware")
    current = now if now is not None else datetime.now(timezone.utc)
    if type(current) is not datetime or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Current time must be timezone-aware")
    if type(max_age_seconds) is not int or not 0 < max_age_seconds <= 300:
        raise ValueError("Invalid freshness policy")
    age = (current.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ValueError("Future or stale market observation")
    if type(payload["price"]) not in (str, Decimal):
        raise ValueError("Price must be exact decimal")
    try:
        price = Decimal(payload["price"])
        if not price.is_finite() or not Decimal("0.01") <= price <= Decimal("1000000") or price != price.quantize(Decimal("0.01")):
            raise ValueError("Invalid market price")
    except (InvalidOperation, OverflowError):
        raise ValueError("Invalid market price") from None
    return {"provider": provider, "symbol": expected_symbol,
            "timestamp_utc": observed.astimezone(timezone.utc).isoformat(),
            "price": format(price, ".2f"), "authenticated": True,
            "execution_authorized": False}
