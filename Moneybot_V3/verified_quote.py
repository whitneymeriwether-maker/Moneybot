"""Strict boundary for authenticated paper-market observations.

This module does not fetch quotes or authorize fills. A future authenticated
provider adapter must supply the observation and its verified provenance.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")
_PRICE = re.compile(r"(0|[1-9][0-9]*)(?:\.[0-9]{1,4})?")
_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{1,39}")


def verify_quote(observation, *, expected_symbol, now=None, max_age_seconds=90):
    """Return normalized quote or fail closed; never accept self-asserted auth.

    verified_transport must be supplied by trusted adapter code, not copied
    from provider JSON. Timestamp is an exchange/provider observation time,
    never the local ingestion time.
    """
    if not isinstance(observation, dict):
        raise ValueError("missing quote")
    if observation.get("verified_transport") is not True:
        raise ValueError("unverified market-data transport")
    provider = observation.get("provider")
    if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
        raise ValueError("invalid provider")
    symbol = observation.get("symbol")
    if not isinstance(expected_symbol, str) or not _SYMBOL.fullmatch(expected_symbol):
        raise ValueError("invalid expected symbol")
    if symbol != expected_symbol:
        raise ValueError("symbol mismatch")
    price = observation.get("price")
    if not isinstance(price, str) or len(price) > 24 or not _PRICE.fullmatch(price):
        raise ValueError("invalid quote price")
    try:
        parsed = Decimal(price)
    except InvalidOperation:
        raise ValueError("invalid quote price") from None
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal("1000000"):
        raise ValueError("quote outside supported bounds")
    timestamp = observation.get("observed_at")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ValueError("quote timestamp must be UTC")
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid quote timestamp") from None
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("current time must be timezone aware")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or not 0 < max_age_seconds <= 300:
        raise ValueError("invalid freshness policy")
    age = (current.astimezone(timezone.utc) - observed).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ValueError("stale or future quote")
    return {"provider": provider, "symbol": symbol, "price": str(parsed), "observed_at": timestamp}
