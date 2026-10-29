"""Reject untraded breakout signals in offline paper simulation.

All bars and signals are synthetic. No market APIs or brokerage activity.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backtesting.trade_simulator import simulate_trades


START = datetime(2026, 10, 12, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def bar(minute, *, volume):
    return SimpleNamespace(
        timestamp=START + timedelta(minutes=minute),
        open=102.0, high=103.0, low=101.0, close=102.0,
        volume=volume,
    )


def signal(*, with_metadata):
    fields = dict(
        timestamp=START,
        opening_range_high=101.0,
        opening_range_low=99.0,
    )
    if with_metadata:
        fields.update(entry_price=102.0, vwap=100.0)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize("with_metadata", [False, True])
def test_zero_volume_signal_bar_is_rejected(with_metadata):
    # A next-minute traded bar cannot retroactively validate a breakout
    # allegedly observed on a minute with no prints.
    tape = [bar(0, volume=0), bar(1, volume=1000)]
    with pytest.raises(ValueError, match="no observed trades"):
        simulate_trades(tape, [signal(with_metadata=with_metadata)])


@pytest.mark.parametrize("with_metadata", [False, True])
def test_traded_signal_bar_remains_eligible(with_metadata):
    tape = [bar(0, volume=1000), bar(1, volume=1000)]
    trades = simulate_trades(
        tape, [signal(with_metadata=with_metadata)], slippage_pct=0,
    )
    assert len(trades) == 1
    assert trades[0].entry_time == START + timedelta(minutes=1)


def test_zero_volume_bar_without_a_signal_does_not_error():
    assert simulate_trades(
        [bar(0, volume=0), bar(1, volume=1000)], [], slippage_pct=0,
    ) == []
