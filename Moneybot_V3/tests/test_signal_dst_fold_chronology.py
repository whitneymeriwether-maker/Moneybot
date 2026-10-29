"""DST-fold chronology checks for offline historical signal scanning."""

from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backtesting.historical_data import PriceBar
from backtesting.signals import generate_breakout_signals


NEW_YORK = ZoneInfo("America/New_York")


def bar(minute, fold):
    # New York repeats 01:00-01:59 on Sunday, November 1, 2026.
    at = datetime(2026, 11, 1, 1, minute, fold=fold, tzinfo=NEW_YORK)
    return PriceBar(at, 100.0, 101.0, 99.0, 100.0, 1000)


def test_repeated_local_minute_with_distinct_utc_instants_is_valid():
    first, second = bar(30, 0), bar(30, 1)
    assert first.timestamp.astimezone(timezone.utc) < second.timestamp.astimezone(timezone.utc)
    assert generate_breakout_signals([first, second]) == []


def test_wall_clock_can_move_backward_while_utc_advances():
    first, second = bar(45, 0), bar(15, 1)
    assert first.timestamp.astimezone(timezone.utc) < second.timestamp.astimezone(timezone.utc)
    assert generate_breakout_signals([first, second]) == []


def test_reversed_utc_instants_across_fold_are_rejected():
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals([bar(30, 1), bar(30, 0)])


def test_timezone_equivalent_duplicate_instant_is_rejected():
    first = bar(30, 0)
    second = replace(first, timestamp=first.timestamp.astimezone(timezone.utc))
    with pytest.raises(ValueError, match="strictly increasing"):
        generate_breakout_signals([first, second])
