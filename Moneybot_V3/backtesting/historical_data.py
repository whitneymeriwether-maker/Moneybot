
"""Historical stock-price reader for V3 research backtesting."""

import csv
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path


@dataclass(frozen=True)
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def load_price_bars(filename):
    """Read and validate OHLCV prices from a CSV file."""
    bars = []
    previous_timestamp = None

    with Path(filename).open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        required = {
            "timestamp", "open", "high", "low", "close", "volume"
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Missing required CSV columns")

        for row in reader:
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
            if volume < 0:
                raise ValueError("Negative volume")

            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp must include timezone")

            if previous_timestamp is not None and timestamp <= previous_timestamp:
                raise ValueError("Timestamps must be increasing")

            bars.append(
                PriceBar(timestamp, opening, high, low, close, volume)
            )
            previous_timestamp = timestamp

    if not bars:
        raise ValueError("No historical prices found")

    return bars
