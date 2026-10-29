"""Chronological provenance checks for direct V3 breakout scanning.

Synthetic OHLCV only; no market-data requests or brokerage activity.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backtesting.historical_data import PriceBar
from backtesting.signals import generate_breakout_signals


NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 12, 9, 30, tzinfo=NY)


def bar(minute, *, close=100.0):
    at = START + timedelta(minutes=minute)
    return PriceBar(
        timestamp=at,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
    )


def test_duplicate_opening_minute_is_rejected_instead_of_double_counted():
    tape = [bar(i) for i in range(15)]
    tape.insert(7, tape[6])
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals(tape)


def test_reversed_minutes_are_rejected_even_without_a_breakout():
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals([bar(1), bar(0)])


def test_reversal_in_prior_session_is_not_hidden_by_later_valid_session():
    tape = [bar(1), bar(0), replace(bar(2), timestamp=bar(2).timestamp + timedelta(days=1))]
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals(tape)


def test_naive_direct_scanner_timestamp_is_rejected():
    invalid = replace(bar(0), timestamp=START.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_breakout_signals([invalid])


def test_offset_with_seconds_cannot_disguise_a_nonminute_utc_instant():
    offset = timezone(timedelta(hours=-5, seconds=30))
    invalid = replace(bar(0), timestamp=datetime(2026, 1, 5, 9, 30, tzinfo=offset))
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        generate_breakout_signals([invalid])


def test_fractional_second_bar_is_rejected():
    invalid = replace(bar(0), timestamp=START + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        generate_breakout_signals([invalid])


def test_equivalent_utc_and_new_york_timestamps_preserve_valid_breakout():
    tape = [bar(i) for i in range(15)] + [bar(15, close=103.0)]
    tape[4] = replace(tape[4], timestamp=tape[4].timestamp.astimezone(timezone.utc))
    signals = generate_breakout_signals(tape)
    assert len(signals) == 1
    assert signals[0].timestamp == tape[-1].timestamp
