"""Strict market quote boundary for future PAPER-ONLY execution.

Pure validation; does not connect to a provider, schedule, or submit orders.
An upstream authenticated adapter must attest transport and provider identity.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re

SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")

class UnverifiedMarketData(ValueError):
    pass

def verified_quote(payload, *, expected_symbol, now=None, max_age_seconds=90):
    """Return validated price and UTC observation time; reject uncertain provenance."""
    if not isinstance(payload, dict) or not SYMBOL.fullmatch(expected_symbol):
        raise UnverifiedMarketData("invalid quote or symbol")
    if payload.get("symbol") != expected_symbol:
        raise UnverifiedMarketData("symbol mismatch")
    if payload.get("authenticated_transport") is not True or payload.get("provider_verified") is not True:
        raise UnverifiedMarketData("market-data authentication not established")
    if not isinstance(payload.get("provider"), str) or not payload["provider"].strip():
        raise UnverifiedMarketData("provider identity missing")
    raw = payload.get("price")
    if not isinstance(raw, str) or not re.fullmatch(r"(0|[1-9][0-9]*)(\.[0-9]{1,6})?", raw):
        raise UnverifiedMarketData("invalid price representation")
    try:
        price = Decimal(raw)
    except InvalidOperation as exc:
        raise UnverifiedMarketData("invalid price") from exc
    if not price.is_finite() or price <= 0 or price > Decimal("10000000"):
        raise UnverifiedMarketData("price out of bounds")
    stamp = payload.get("timestamp_utc")
    if not isinstance(stamp, str):
        raise UnverifiedMarketData("timestamp missing")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UnverifiedMarketData("timestamp invalid") from exc
    if observed.tzinfo is None or observed.utcoffset() != timedelta(0):
        raise UnverifiedMarketData("timestamp must be UTC")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timedelta(0):
        raise UnverifiedMarketData("clock must be UTC")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or not 0 < max_age_seconds <= 300:
        raise UnverifiedMarketData("invalid freshness policy")
    age = (current - observed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise UnverifiedMarketData("future or stale quote")
    return {"symbol": expected_symbol, "price": price, "observed_at": observed, "provider": payload["provider"]}
