
"""Market capitalization data for Moneybot V3 research.

Uses Financial Modeling Prep (FMP).
Read-only research. No brokerage orders.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from backtesting.download_data import validate_symbol


FMP_BASE_URL = "https://financialmodelingprep.com/stable"
MAX_DATA_AGE_DAYS = 7


class MarketCapDataError(RuntimeError):
    """Raised when verified market-cap data is unavailable."""


def get_market_cap(symbol):
    """Retrieve and validate a stock's reported market cap."""

    symbol = validate_symbol(symbol)

    api_key = os.environ.get("FMP_API_KEY")

    if not api_key:
        raise MarketCapDataError(
            "Missing FMP_API_KEY. "
            "Configure it as a GitHub Actions secret."
        )

    params = urlencode({
        "symbol": symbol,
        "apikey": api_key,
    })

    url = f"{FMP_BASE_URL}/market-capitalization?{params}"

    request = Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, ValueError) as error:
        raise MarketCapDataError(
            f"Unable to retrieve market cap for {symbol}"
        ) from error

    if not isinstance(payload, list) or not payload:
        raise MarketCapDataError(
            f"No market-cap data returned for {symbol}"
        )

    matching_records = [
        record
        for record in payload
        if isinstance(record, dict)
        and record.get("symbol", "").upper() == symbol
    ]

    if not matching_records:
        raise MarketCapDataError(
            f"No matching market-cap record for {symbol}"
        )

    record = matching_records[0]

    value = record.get("marketCap")

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise MarketCapDataError(
            f"Invalid market capitalization for {symbol}"
        )

    # A current market-cap endpoint does not necessarily
    # supply a reliable observation timestamp. Do not
    # invent one or claim historical verification.
    return float(value)


if __name__ == "__main__":
    print("Moneybot V3 Market Capitalization Data")
    print("Provider: Financial Modeling Prep")
    print("API key required for real requests.")
    print("Current data only; not historical backtest data.")
    print("No brokerage orders submitted.")
