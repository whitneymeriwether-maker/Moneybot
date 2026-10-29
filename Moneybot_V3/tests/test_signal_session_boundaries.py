"""Session-bound signal provenance checks for offline V3 paper research."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backtesting.trade_simulator import simulate_trades


NY = ZoneInfo("America/New_York")


def bar(at):
    return SimpleNamespace(
        timestamp=at, open=100.0, high=101.0, low=99.0,
        close=100.0, volume=1000,
    )


def signal(at):
    return SimpleNamespace(
        timestamp=at, opening_range_high=101.0,
        opening_range_low=99.0,
    )


@pytest.mark.parametrize("day,hour,minute", [
    (12, 9, 29),   # Premarket cannot trigger a 9:30 entry.
    (12, 9, 44),   # The opening range is not complete.
    (12, 16, 0),   # Closing auction/after-hours is not a signal.
    (12, 16, 1),
    (11, 9, 45),   # Sunday cannot produce a US equity breakout.
])
def test_off_session_external_signals_fail_closed(day, hour, minute):
    at = datetime(2026, 10, day, hour, minute, tzinfo=NY)
    bars = [bar(at), bar(at + timedelta(minutes=1))]
    with pytest.raises(ValueError, match="outside eligible breakout session"):
        simulate_trades(bars, [signal(at)], slippage_pct=0)


def test_valid_first_breakout_minute_remains_supported():
    at = datetime(2026, 10, 12, 9, 45, tzinfo=NY)
    bars = [bar(at), bar(at + timedelta(minutes=1))]
    trades = simulate_trades(bars, [signal(at)], slippage_pct=0)
    assert len(trades) == 1
    assert trades[0].entry_time == bars[1].timestamp


def test_timezone_equivalent_first_breakout_minute_is_supported():
    at = datetime(2026, 10, 12, 9, 45, tzinfo=NY)
    bars = [bar(at), bar(at + timedelta(minutes=1))]
    trades = simulate_trades(
        bars, [signal(at.astimezone(timezone.utc))], slippage_pct=0
    )
    assert len(trades) == 1


def test_last_regular_minute_signal_is_accepted_but_cannot_fill_after_close():
    at = datetime(2026, 10, 12, 15, 59, tzinfo=NY)
    bars = [bar(at), bar(at + timedelta(minutes=1))]
    assert simulate_trades(bars, [signal(at)], slippage_pct=0) == []
