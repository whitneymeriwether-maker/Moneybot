
"""Tests for Moneybot V3 opening-range breakout signals."""

import sys
import pytest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_data import PriceBar
from backtesting.signals import generate_breakout_signals


EASTERN = timezone(timedelta(hours=-5))


def make_bar(hour, minute, close, high=None, low=None, volume=1000):
    timestamp = datetime(
        2026, 1, 5, hour, minute, tzinfo=EASTERN
    )
    return PriceBar(
        timestamp=timestamp,
        open=close,
        high=high if high is not None else close + 0.1,
        low=low if low is not None else close - 0.1,
        close=close,
        volume=volume,
    )


def opening_range():
    return [
        make_bar(9, minute, 100, high=101, low=99)
        for minute in range(30, 45)
    ]


def test_detects_breakout():
    bars = opening_range()
    bars.append(make_bar(9, 45, 102, high=102.5, low=101.5))

    signals = generate_breakout_signals(bars)

    assert len(signals) == 1
    assert signals[0].entry_price == 102
    assert signals[0].opening_range_high == 101


def test_no_breakout_below_range():
    bars = opening_range()
    bars.append(make_bar(9, 45, 100.5))

    assert generate_breakout_signals(bars) == []


def test_no_signal_during_opening_range():
    bars = opening_range()

    assert generate_breakout_signals(bars) == []


def test_only_one_signal_per_day():
    bars = opening_range()
    bars.append(make_bar(9, 45, 102))
    bars.append(make_bar(9, 46, 103))

    assert len(generate_breakout_signals(bars)) == 1


def test_zero_volume_breakout_cannot_generate_signal():
    bars = opening_range()
    bars.append(
        make_bar(9, 45, 102, high=102.5, low=101.5, volume=0)
    )

    assert generate_breakout_signals(bars) == []


def test_later_traded_breakout_after_zero_volume_minute():
    bars = opening_range()
    bars.append(make_bar(9, 45, 102, high=102.5, low=101.5, volume=0))
    bars.append(make_bar(9, 46, 102, high=102.5, low=101.5, volume=1000))

    signals = generate_breakout_signals(bars)

    assert len(signals) == 1
    assert signals[0].timestamp == bars[-1].timestamp
    assert signals[0].entry_price > signals[0].vwap


def test_zero_volume_opening_minute_makes_range_incomplete():
    bars = opening_range()
    bars[5] = make_bar(9, 35, 100, high=101, low=99, volume=0)
    bars.append(make_bar(9, 45, 102, high=102.5, low=101.5))

    assert generate_breakout_signals(bars) == []


def test_no_signal_before_market_open():
    bars = [make_bar(9, 20, 105)]

    assert generate_breakout_signals(bars) == []


def test_no_signal_without_opening_range():
    bars = [make_bar(10, 0, 105)]

    assert generate_breakout_signals(bars) == []


def test_rejects_incomplete_opening_range():
    bars = opening_range()

    # Remove the 9:35 AM bar.
    bars = [
        bar for bar in bars
        if bar.timestamp.minute != 35
    ]

    bars.append(make_bar(9, 45, 105))

    signals = generate_breakout_signals(bars)

    assert signals == []


def test_duplicate_minute_does_not_replace_missing_minute():
    bars = opening_range()

    # Remove 9:35 and duplicate 9:34 instead.
    bars = [
        bar for bar in bars
        if bar.timestamp.minute != 35
    ]

    bars.append(make_bar(9, 34, 100, high=101, low=99))
    bars.sort(key=lambda bar: bar.timestamp)
    bars.append(make_bar(9, 45, 105))

    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals(bars)


def test_weekend_opening_range_never_generates_signal():
    """A synthetic Sunday session cannot be mistaken for Monday trading."""
    monday_bars = opening_range()
    monday_bars.append(make_bar(9, 45, 102, high=102.5, low=101.5))
    sunday_bars = [
        replace(bar, timestamp=bar.timestamp - timedelta(days=1))
        for bar in monday_bars
    ]
    assert sunday_bars[0].timestamp.weekday() == 6
    assert generate_breakout_signals(sunday_bars) == []
