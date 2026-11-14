"""Read-only operational smoke test for authenticated Alpaca IEX market data.

Usage: python Moneybot_V3/market_data_smoke.py SPY
Requires APCA_API_KEY_ID and APCA_API_SECRET_KEY. Never places orders,
writes paper fills, prints credentials, or treats a quote as executable.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from .alpaca_market_data import latest_alpaca_quote
except ImportError:
    from alpaca_market_data import latest_alpaca_quote


def probe(symbol, *, fetcher=latest_alpaca_quote, now=None):
    """Return a safe, non-executable result; failures never fall back to demo data."""
    current = now if now is not None else datetime.now(timezone.utc)
    if type(symbol) is not str or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise ValueError("Invalid symbol")
    quote = fetcher(symbol, now=current)
    if (type(quote) is not dict or quote.get("authenticated") is not True
        or quote.get("execution_authorized") is not False
        or quote.get("symbol") != symbol or quote.get("provider") != "alpaca"
        or quote.get("feed") != "iex"
        or quote.get("price_type") != "bid_ask_midpoint_not_execution"):
        raise ValueError("Unverified market observation")
    return {
        "ok": True, "source": "authenticated_alpaca_iex",
        "symbol": symbol, "observed_at": quote["timestamp_utc"],
        "research_midpoint": quote["price"], "paper_trading_enabled": False,
        "broker_orders_enabled": False, "executable_fill": False,
    }


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: market_data_smoke.py SYMBOL", file=sys.stderr)
        return 2
    try:
        result = probe(args[0])
    except (ValueError, OSError, TimeoutError, KeyError, TypeError):
        # Do not expose HTTP exceptions, response bodies or credential strings.
        print(json.dumps({"ok": False, "reason": "market_data_unavailable_or_unverified",
                          "paper_trading_enabled": False}), file=sys.stdout)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
