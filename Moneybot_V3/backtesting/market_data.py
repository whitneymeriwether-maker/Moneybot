
"""Read-only Alpaca market data for Moneybot V3 research.

No brokerage orders or live trading.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backtesting.download_data import validate_symbol
from backtesting.stock_screener import StockCandidate


DATA_BASE = "https://data.alpaca.markets/v2/stocks"
ASSETS_BASE = "https://paper-api.alpaca.markets/v2/assets"


def _credentials():
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError(
            "Missing Alpaca credentials. "
            "Use GitHub Actions secrets."
        )

    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


def _get_json(url):
    """Make an authenticated, read-only GET request."""

    request = Request(
        url,
        headers=_credentials(),
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError) as error:
        raise RuntimeError(
            "Alpaca market data request failed"
        ) from error


def get_latest_quote(symbol):
    """Return the latest available IEX bid and ask."""

    symbol = validate_symbol(symbol)

    url = (
        f"{DATA_BASE}/{quote(symbol, safe='')}/quotes/latest?"
        + urlencode({"feed": "iex"})
    )

    payload = _get_json(url)
    quote_data = payload.get("quote") or {}

    bid = quote_data.get("bp")
    ask = quote_data.get("ap")

    if bid is None or ask is None:
        raise RuntimeError(
            f"Missing bid-ask quote for {symbol}"
        )

    return float(bid), float(ask)


def get_recent_daily_bars(symbol, days=45):
    """Fetch recent daily bars using the IEX feed."""

    symbol = validate_symbol(symbol)

    if not isinstance(days, int) or not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    params = {
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 1000,
        "feed": "iex",
        "adjustment": "raw",
    }

    url = (
        f"{DATA_BASE}/{quote(symbol, safe='')}/bars?"
        + urlencode(params)
    )

    bars = []
    next_page_token = None

    while True:
        page_params = dict(params)

        if next_page_token:
            page_params["page_token"] = next_page_token

        page_url = (
            f"{DATA_BASE}/{quote(symbol, safe='')}/bars?"
            + urlencode(page_params)
        )

        payload = _get_json(page_url)
        bars.extend(payload.get("bars") or [])

        next_page_token = payload.get("next_page_token")

        if not next_page_token:
            break

    return sorted(bars, key=lambda bar: bar["t"])


def get_stock_candidate(symbol, market_cap):
    """Build a candidate for the V3 stock screener.

    Market capitalization must come from a separate,
    verified, time-appropriate data source. Alpaca's
    standard stock bars do not provide market cap.
    """

    symbol = validate_symbol(symbol)

    if isinstance(market_cap, bool) or not isinstance(
        market_cap, (int, float)
    ):
        raise ValueError("A numeric market cap is required")

    bars = get_recent_daily_bars(symbol)

    if len(bars) < 20:
        raise RuntimeError(
            f"Not enough daily bars for {symbol}: "
            f"{len(bars)} available; 20 required"
        )

    recent = bars[-20:]

    average_daily_volume = (
        sum(float(bar["v"]) for bar in recent) / len(recent)
    )

    price = float(recent[-1]["c"])
    bid, ask = get_latest_quote(symbol)

    return StockCandidate(
        symbol=symbol,
        price=price,
        average_daily_volume=average_daily_volume,
        market_cap=market_cap,
        bid=bid,
        ask=ask,
    )


if __name__ == "__main__":
    print("Moneybot V3 Market Data")
    print("Alpaca IEX data: read-only")
    print("Market cap requires a separate verified source.")
    print("No brokerage orders submitted.")
