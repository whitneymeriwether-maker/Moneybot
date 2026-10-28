
"""Historical stock-price reader for V3 research backtesting."""

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

# Python's ISO parser accepts compact/week dates and nonstandard offsets.
# Require an explicit canonical UTC offset for historical research tapes.
_RFC3339_MINUTE_BAR = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?P<fraction>\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


@dataclass(frozen=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def load_price_bars(filename, expected_symbol=None):
    """Read and validate OHLCV, optionally requiring matching ticker metadata.

    Without expected_symbol, legacy unlabelled exploratory CSVs are allowed.
    When a symbol column is present, every row must identify one same valid
    ticker; an expected symbol additionally requires the column to exist.
    """
    if expected_symbol is not None and (
        type(expected_symbol) is not str
        or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", expected_symbol)
    ):
        raise ValueError("Invalid expected historical symbol")
    bars = []
    previous_timestamp = None
    observed_symbol = None

    with Path(filename).open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        required = {
            "timestamp", "open", "high", "low", "close", "volume"
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Missing required CSV columns")
        # DictReader silently overwrites duplicate header names. A
        # duplicated OHLCV column could therefore change prices or volume
        # without any indication that the source file was malformed.
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Duplicate historical CSV columns")
        if any(not name for name in reader.fieldnames):
            raise ValueError("Unnamed historical CSV column")
        if expected_symbol is not None and "symbol" not in reader.fieldnames:
            raise ValueError("Historical CSV missing symbol metadata")

        for row in reader:
            # DictReader stores surplus cells under None and fills absent
            # cells with None. Never silently ignore truncated/overlong bars.
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed historical CSV row")
            if "symbol" in reader.fieldnames:
                symbol = row["symbol"]
                if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
                    raise ValueError("Invalid historical symbol metadata")
                if observed_symbol is not None and symbol != observed_symbol:
                    raise ValueError("Mixed symbols in historical CSV")
                if expected_symbol is not None and symbol != expected_symbol:
                    raise ValueError("Historical symbol does not match expected symbol")
                observed_symbol = symbol
            timestamp = datetime.fromisoformat(row["timestamp"])
            opening = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            volume = int(row["volume"])

            prices = (opening, high, low, close)
            if not all(isfinite(value) and value > 0 for value in prices):
                raise ValueError("Invalid price")

            if high < max(opening, close, low):
                raise ValueError("High price is inconsistent")
            if low > min(opening, close, high):
                raise ValueError("Low price is inconsistent")
            # int() accepts arbitrarily large CSV integers, but such a
            # volume cannot be used safely in floating-point VWAP math.
            try:
                valid_volume = volume >= 0 and isfinite(volume)
            except OverflowError:
                valid_volume = False
            if not valid_volume:
                raise ValueError("Invalid historical volume")

            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")
            # A minute-aligned local timestamp can still represent a half-minute
            # UTC instant when the supplied offset includes seconds. Research
            # bars must be aligned to both the source clock and UTC.
            utc_timestamp = timestamp.astimezone(timezone.utc)
            if (
                timestamp.second or timestamp.microsecond
                or utc_timestamp.second or utc_timestamp.microsecond
            ):
                raise ValueError("Historical minute bar must be UTC minute-aligned")

            match = _RFC3339_MINUTE_BAR.fullmatch(row["timestamp"])
            if match is None:
                raise ValueError("Noncanonical historical CSV timestamp")
            # datetime.fromisoformat truncates fractional nanoseconds: even
            # .000000001 is not an exact minute, despite microsecond == 0.
            fraction = match.group("fraction")
            if fraction is not None and any(digit != "0" for digit in fraction[1:]):
                raise ValueError("Historical minute bar must be UTC minute-aligned")

            if previous_timestamp is not None and timestamp <= previous_timestamp:
                raise ValueError("Timestamps must be increasing")

            bars.append(
                PriceBar(timestamp, opening, high, low, close, volume)
            )
            previous_timestamp = timestamp

    if not bars:
        raise ValueError("No historical prices found")

    return bars
