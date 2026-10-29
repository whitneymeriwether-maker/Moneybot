"""Offline regressions for direct simulator DST chronology.

No provider access, orders, or network operations.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.trade_simulator import simulate_trades


NY = ZoneInfo("America/New_York")


def bar(timestamp):
    return SimpleNamespace(
        timestamp=timestamp,
        open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
    )


def test_simulator_accepts_chronological_repeated_dst_hour():
    # Both 01:30 clocks exist on 2026-11-01, an hour apart in UTC.
    first = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=1)
    assert first.astimezone(timezone.utc) < second.astimezone(timezone.utc)
    assert simulate_trades([bar(first), bar(second)], []) == []


def test_simulator_accepts_backward_wall_clock_when_utc_increases():
    first = datetime(2026, 11, 1, 1, 59, tzinfo=NY, fold=0)
    second = datetime(2026, 11, 1, 1, 0, tzinfo=NY, fold=1)
    assert first.astimezone(timezone.utc) < second.astimezone(timezone.utc)
    assert simulate_trades([bar(first), bar(second)], []) == []


def test_simulator_rejects_forward_wall_clock_when_utc_reverses():
    later = datetime(2026, 11, 1, 1, 0, tzinfo=NY, fold=1)
    earlier = datetime(2026, 11, 1, 1, 59, tzinfo=NY, fold=0)
    assert later.astimezone(timezone.utc) > earlier.astimezone(timezone.utc)
    with pytest.raises(ValueError, match="strictly increasing"):
        simulate_trades([bar(later), bar(earlier)], [])


def test_simulator_rejects_reversed_repeated_wall_minute():
    first = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=1)
    with pytest.raises(ValueError, match="strictly increasing"):
        simulate_trades([bar(second), bar(first)], [])
