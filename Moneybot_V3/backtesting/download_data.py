
"""Download historical minute bars for Moneybot V3 research.

Read-only market data. No brokerage orders.
"""

import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

# Support both "python -m backtesting.download_data" and the existing
# GitHub Actions invocation "python backtesting/download_data.py".
if __package__:
    from .historical_data import load_price_bars
else:
    from historical_data import load_price_bars
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"

START = "2026-04-01T00:00:00Z"
END = "2026-10-01T00:00:00Z"

# SPY remains the default so the existing historical workflow
# continues to work without changes.
DEFAULT_SYMBOL = "SPY"

# Experimental research universe, not an automatic stock filter.
RESEARCH_MIN_PRICE = 2.00
RESEARCH_MAX_PRICE = 30.00


def validate_symbol(symbol):
    """Allow conventional stock ticker symbols only."""
    symbol = symbol.strip().upper()

    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise ValueError(f"Invalid stock symbol: {symbol!r}")

    return symbol


def download_history(symbol=None):
    """Download six months of minute bars for one stock."""

    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError(
            "Missing Alpaca market-data credentials. "
            "Use GitHub Actions secrets, not hardcoded keys."
        )

    if symbol is None:
        symbol = os.environ.get(
            "MONEYBOT_V3_SYMBOL",
            DEFAULT_SYMBOL,
        )

    symbol = validate_symbol(symbol)

    output_name = f"{symbol}_1min_2026_04_to_09.csv"

    output = (
        Path(__file__).resolve().parents[1]
        / "data"
        / output_name
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    bars = []
    next_page_token = None
    seen_page_tokens = set()

    # Six months of minute bars cannot require 100 pages at 10,000
    # bars per page. Reject cyclic or malformed pagination.
    for _ in range(100):
        params = {
            "symbols": symbol,
            "timeframe": "1Min",
            "start": START,
            "end": END,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }

        if next_page_token:
            params["page_token"] = next_page_token

        url = DATA_URL + "?" + urlencode(params)

        request = Request(
            url,
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (HTTPError, URLError) as error:
            raise RuntimeError(
                f"Historical data download failed for {symbol}"
            ) from error

        if not isinstance(payload, dict):
            raise RuntimeError(f"Invalid historical response for {symbol}")
        symbol_bars = payload.get("bars")
        if not isinstance(symbol_bars, dict):
            raise RuntimeError(f"Invalid historical response for {symbol}")
        page_bars = symbol_bars.get(symbol, [])
        if not isinstance(page_bars, list):
            raise RuntimeError(f"Invalid historical response for {symbol}")
        bars.extend(page_bars)

        next_page_token = payload.get("next_page_token")
        if next_page_token is None:
            break
        if (
            not isinstance(next_page_token, str)
            or not next_page_token.strip()
            or next_page_token in seen_page_tokens
        ):
            raise RuntimeError(f"Invalid historical pagination for {symbol}")
        seen_page_tokens.add(next_page_token)
    else:
        raise RuntimeError(f"Historical pagination limit reached for {symbol}")

    if not bars:
        raise RuntimeError(
            f"Alpaca returned no historical bars for {symbol}"
        )

    # Validate the provider's requested UTC window before writing anything.
    # Sorting ISO timestamp strings is unsafe when pages contain different
    # explicit UTC offsets; order by normalized instants instead.
    start_utc = datetime.fromisoformat(START.replace("Z", "+00:00"))
    end_utc = datetime.fromisoformat(END.replace("Z", "+00:00"))
    normalized_bars = []
    for bar in bars:
        timestamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Historical bar timestamp must include timezone")
        timestamp = timestamp.astimezone(timezone.utc)
        if not start_utc <= timestamp < end_utc:
            raise ValueError("Historical bar outside requested UTC window")
        normalized_bars.append((timestamp, bar))
    normalized_bars.sort(key=lambda item: item[0])

    # Validate the full dataset before replacing a previously good CSV.
    # A malformed bar must not corrupt the research history.
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{symbol}-",
            suffix=".csv",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            writer = csv.writer(file)
            writer.writerow([
                "timestamp", "open", "high", "low", "close", "volume",
            ])

            for timestamp, bar in normalized_bars:
                writer.writerow([
                    timestamp.isoformat(),
                    bar["o"],
                    bar["h"],
                    bar["l"],
                    bar["c"],
                    bar["v"],
                ])

        load_price_bars(temporary)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    print(f"Symbol: {symbol}")
    print(f"Downloaded bars: {len(bars)}")
    print(f"Saved historical data: {output}")
    print("Research data only. No orders submitted.")

    return output


if __name__ == "__main__":
    download_history()
