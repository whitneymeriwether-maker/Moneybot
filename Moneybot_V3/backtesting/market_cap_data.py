
"""Market capitalization data for Moneybot V3 research.

Uses Financial Modeling Prep (FMP).
Read-only research. No brokerage orders.
"""

import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backtesting.download_data import validate_symbol


FMP_BASE_URL = "https://financialmodelingprep.com/stable"


class MarketCapDataError(RuntimeError):
    """Raised when market-cap data is unavailable."""


def _valid_positive_number(value):
    """Reject malformed, non-finite, and unrepresentably large values."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value > 0
    except (OverflowError, ValueError):
        return False


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

    except HTTPError as error:
        # Report only the HTTP status, not the request URL.
        # The URL contains the secret API key.
        raise MarketCapDataError(
            f"FMP HTTP {error.code} for {symbol}"
        ) from None

    except URLError:
        raise MarketCapDataError(
            f"FMP network connection failed for {symbol}"
        ) from None

    except (ValueError, UnicodeError):
        raise MarketCapDataError(
            f"FMP returned invalid JSON for {symbol}"
        ) from None

    if not isinstance(payload, list) or not payload:
        raise MarketCapDataError(
            f"No market-cap records returned for {symbol}"
        )

    matching_records = [
        record
        for record in payload
        if isinstance(record, dict)
        and isinstance(record.get("symbol"), str)
        and record["symbol"].upper() == symbol
    ]

    if not matching_records:
        raise MarketCapDataError(
            f"No matching market-cap record for {symbol}"
        )

    value = matching_records[0].get("marketCap")

    if not _valid_positive_number(value):
        raise MarketCapDataError(
            f"Invalid market capitalization for {symbol}"
        )

    return float(value)


if __name__ == "__main__":
    print("Moneybot V3 Market Capitalization Data")
    print("Provider: Financial Modeling Prep")
    print("Current data only; not historical backtest data.")
    print("Read-only research. No brokerage orders.")
