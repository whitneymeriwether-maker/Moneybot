
"""Read-only Alpaca market data for Moneybot V3 research.

IEX volume is partial-market volume, not consolidated volume.
Quotes are validated for price integrity and basic freshness.

No brokerage orders or live trading.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backtesting.download_data import validate_symbol
from backtesting.stock_screener import StockCandidate


DATA_BASE = "https://data.alpaca.markets/v2/stocks"
ASSETS_BASE = "https://paper-api.alpaca.markets/v2/assets"

MAX_QUOTE_AGE = timedelta(hours=72)


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


def _parse_quote_timestamp(value):
    """Convert an Alpaca timestamp to UTC."""

    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("Missing quote timestamp")

    try:
        timestamp = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError:
        raise RuntimeError("Invalid quote timestamp") from None

    if timestamp.tzinfo is None:
        raise RuntimeError("Invalid quote timestamp")

    return timestamp.astimezone(timezone.utc)


def get_latest_quote(symbol):
    """Return validated IEX bid and ask prices."""

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

    timestamp = _parse_quote_timestamp(
        quote_data.get("t")
    )

    age = datetime.now(timezone.utc) - timestamp

    if age > MAX_QUOTE_AGE or age < timedelta(minutes=-5):
        raise RuntimeError(
            f"Stale quote for {symbol}: "
            f"timestamp {timestamp.isoformat()}"
        )

    try:
        bid = float(bid)
        ask = float(ask)
    except (TypeError, ValueError, OverflowError):
        raise RuntimeError(
            f"Invalid bid-ask quote for {symbol}"
        ) from None

    if (
        not isfinite(bid)
        or not isfinite(ask)
        or bid <= 0
        or ask <= 0
        or bid >= ask
    ):
        raise RuntimeError(
            f"Invalid bid-ask quote for {symbol}"
        )

    return bid, ask


def get_recent_daily_bars(symbol, days=45):
    """Fetch recent daily bars using the partial-market IEX feed."""

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



def _validate_daily_bars(bars, symbol):
    """Fail closed on malformed OHLCV data before screening a stock.

    One IEX daily bar per UTC date is expected. An invalid bar must
    never contribute to the volume average or closing price.
    """

    observed_dates = set()
    now = datetime.now(timezone.utc)

    for bar in bars:
        try:
            timestamp = _parse_quote_timestamp(bar["t"])
            values = [bar[field] for field in ("o", "h", "l", "c", "v")]
            if any(isinstance(value, bool) for value in values):
                raise ValueError("Boolean OHLCV value")
            open_price, high, low, close, volume = map(float, values)
        except (KeyError, TypeError, ValueError, OverflowError, RuntimeError):
            raise RuntimeError(f"Invalid daily bar for {symbol}") from None

        if (
            not all(isfinite(value) for value in (
                open_price, high, low, close, volume
            ))
            or low <= 0
            or volume < 0
            or not low <= min(open_price, close)
            or not max(open_price, close) <= high
            or timestamp > now + timedelta(minutes=5)
            or timestamp.date() in observed_dates
        ):
            raise RuntimeError(f"Invalid daily bar for {symbol}")

        observed_dates.add(timestamp.date())


def get_stock_candidate(symbol, market_cap):
    """Build a research candidate using IEX market data.

    IMPORTANT:
    Average daily volume here is IEX-only volume.
    It must not be represented as consolidated volume.

    Market cap must come from a separate provider.
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
    _validate_daily_bars(recent, symbol)

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
    print("Alpaca IEX data: read-only, partial-market feed")
    print("Quote validation: price integrity and freshness")
    print("No brokerage orders submitted.")
