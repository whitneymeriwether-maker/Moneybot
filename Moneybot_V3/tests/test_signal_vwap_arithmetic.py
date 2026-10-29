"""Reject non-finite VWAP arithmetic in offline historical signal scanning.

These tests use synthetic price bars only; no market APIs or orders.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_data import PriceBar
from backtesting.signals import generate_breakout_signals


EASTERN = timezone(timedelta(hours=-5))


def bar(minute, price, volume):
    return PriceBar(
        timestamp=datetime(2026, 1, 5, 9, minute, tzinfo=EASTERN),
        open=price, high=price, low=price, close=price,
        volume=volume,
    )


def test_large_finite_prices_do_not_overflow_typical_price_sum():
    # Adding three 1e308 prices overflows, but their mean is finite.
    assert generate_breakout_signals([bar(30, 1e308, 1)]) == []


def test_rejects_overflowed_cumulative_price_volume():
    # A finite price and valid integer volume can overflow the VWAP sum.
    with pytest.raises(ValueError, match="VWAP arithmetic"):
        generate_breakout_signals([bar(30, 1e308, 1), bar(31, 1e308, 1)])


def test_rejects_overflowed_weighted_price_volume():
    with pytest.raises(ValueError, match="VWAP arithmetic"):
        generate_breakout_signals([bar(30, 1e308, 1000)])


def test_rejects_unrepresentable_huge_integer_volume():
    with pytest.raises(ValueError, match="Invalid signal bar volume"):
        generate_breakout_signals([bar(30, 100.0, 10 ** 400)])


def test_ordinary_complete_opening_range_still_emits_breakout():
    bars = [bar(minute, 100.0, 1000) for minute in range(30, 45)]
    bars.append(bar(45, 102.0, 1000))
    signals = generate_breakout_signals(bars)
    assert len(signals) == 1
    assert signals[0].entry_price == 102.0
    assert signals[0].vwap < signals[0].entry_price
