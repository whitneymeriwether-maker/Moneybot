"""Authenticated Alpaca market-data adapter for RESEARCH ONLY.

Uses the data API, never the trading/broker API. A successful HTTP response
does not establish a live market session or authorize a hypothetical fill.
Credentials must be supplied in the worker's environment; never logged.
"""
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

try:
    from .verified_market_quote import verified_quote
    from .market_data_boundary import verified_quote as boundary_verified_quote
except ImportError:
    from verified_market_quote import verified_quote
    from market_data_boundary import verified_quote as boundary_verified_quote

_DATA_ORIGIN = "https://data.alpaca.markets"
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def latest_alpaca_quote(symbol, *, key_id=None, secret_key=None, now=None,
                        timeout=8, opener=None):
    """Fetch a validated midpoint observation; never place an order.

    Bid/ask must be positive, non-crossed, cent-precise, and timestamped.
    Feed is explicitly IEX; exchange coverage is not consolidated NBBO.
    """
    if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
        raise ValueError("Invalid market symbol")
    key_id = key_id if key_id is not None else os.environ.get("APCA_API_KEY_ID")
    secret_key = secret_key if secret_key is not None else os.environ.get("APCA_API_SECRET_KEY")
    if not isinstance(key_id, str) or not key_id.strip() or not isinstance(secret_key, str) or not secret_key.strip():
        raise ValueError("Alpaca market-data credentials required")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("Invalid request timeout")
    url = _DATA_ORIGIN + "/v2/stocks/" + urllib.parse.quote(symbol, safe="") + "/quotes/latest?feed=iex"
    request = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    })
    transport = opener if opener is not None else urllib.request.urlopen
    try:
        with transport(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Authenticated market-data request failed")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Market-data response too large")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("Market-data transport unavailable") from None
    try:
        # Reject ambiguous provider JSON rather than silently accepting the last
        # duplicate key (including nested quote fields such as bid and ask).
        def unique_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("Duplicate market-data JSON field")
                obj[key] = value
            return obj
        result = json.loads(raw, object_pairs_hook=unique_object)
        if type(result) is not dict or type(result.get("quote")) is not dict:
            raise ValueError("Missing market quote")
        quote = result["quote"]
        if type(result.get("symbol")) is not str or result["symbol"] != symbol:
            raise ValueError("Market symbol mismatch")
        timestamp = quote["t"]
        if type(timestamp) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)", timestamp):
            raise ValueError("Invalid exchange timestamp")
        # Python datetime supports microseconds; truncate nanosecond precision.
        normalized = timestamp.replace("Z", "+00:00")
        if "." in normalized:
            prefix, suffix = normalized.split(".", 1)
            normalized = prefix + "." + suffix.split("+")[0][:6].ljust(6, "0") + "+00:00"
        observed = datetime.fromisoformat(normalized)
        def decimal_price(value):
            if type(value) not in (str, int, Decimal, float):
                raise ValueError("Invalid bid or ask")
            literal = str(value)
            # Reject oversized and noncanonical provider numbers before parsing.
            if len(literal) > 32 or not re.fullmatch(r"(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,2})?", literal):
                raise ValueError("Invalid bid or ask")
            number = Decimal(literal)
            if not number.is_finite() or number <= 0 or number != number.quantize(Decimal("0.01")):
                raise ValueError("Invalid bid or ask")
            return number
        bid = decimal_price(quote["bp"])
        ask = decimal_price(quote["ap"])
        if ask < bid:
            raise ValueError("Crossed quote")
        midpoint = (bid + ask) / 2
        # Require a cent-precise midpoint rather than silently rounding.
        if midpoint != midpoint.quantize(Decimal("0.01")):
            raise ValueError("Subcent midpoint cannot be represented in paper ledger")
        validated = verified_quote(
            {"symbol": symbol, "timestamp": observed, "price": midpoint},
            provider="alpaca", authenticated=True, expected_symbol=symbol, now=now)
    except (KeyError, TypeError, json.JSONDecodeError, InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid authenticated market-data response") from None
    # Attest provenance only after authenticated HTTPS and strict provider parsing.
    boundary_verified_quote({
        "symbol": symbol, "price": validated["price"],
        "timestamp_utc": validated["timestamp_utc"],
        "provider": "alpaca", "authenticated_transport": True,
        "provider_verified": True,
    }, expected_symbol=symbol, now=now)
    return {**validated, "feed": "iex", "price_type": "bid_ask_midpoint_not_execution",
            "execution_authorized": False}
