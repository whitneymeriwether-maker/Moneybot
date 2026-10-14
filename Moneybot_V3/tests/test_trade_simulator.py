
"""Tests for Moneybot V3's historical trade simulator."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.trade_simulator import simulate_trades


NY = ZoneInfo("America/New_York")


def make_bar(minute, open_price, high, low, close, day=12):
    return SimpleNamespace(
        timestamp=datetime(2026, 10, day, 9, 45, tzinfo=NY)
        + timedelta(minutes=minute),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def make_signal(timestamp):
    return SimpleNamespace(
        timestamp=timestamp,
        opening_range_high=101.0,
        opening_range_low=99.0,
    )


def test_enters_on_next_minute():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert len(trades) == 1
    assert trades[0].entry_time == bars[1].timestamp
    assert trades[0].entry_price == 101


def test_stop_loss():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 100, 101, 98, 99),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades[0].exit_reason == "stop"
    assert trades[0].exit_price == 99


def test_profit_target():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades[0].exit_reason == "target"
    assert trades[0].exit_price == 105


def test_stop_first_when_both_touched():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 101, 106, 98, 102),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades[0].exit_reason == "stop"


def test_position_sizing():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades[0].quantity == 7


def test_cash_limits_share_quantity():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        starting_cash=250,
        risk_per_trade=0.5,
        slippage_pct=0,
    )

    assert len(trades) == 1
    assert trades[0].quantity == 2


def test_slippage_affects_affordability():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 100, 101, 99.5, 100),
        make_bar(2, 100, 101, 99.5, 100),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        starting_cash=100,
        risk_per_trade=0.5,
        slippage_pct=0.01,
    )

    assert trades == []


def test_cash_restored_after_sale():
    first_day = [
        make_bar(0, 100, 101, 99, 100, day=12),
        make_bar(1, 100, 101, 99.5, 100, day=12),
        make_bar(2, 100, 105, 99.5, 104, day=12),
    ]

    second_day = [
        make_bar(0, 100, 101, 99, 100, day=13),
        make_bar(1, 100, 101, 99.5, 100, day=13),
        make_bar(2, 100, 105, 99.5, 104, day=13),
    ]

    bars = first_day + second_day

    signals = [
        make_signal(first_day[0].timestamp),
        make_signal(second_day[0].timestamp),
    ]

    trades = simulate_trades(
        bars,
        signals,
        starting_cash=100,
        risk_per_trade=0.5,
        slippage_pct=0,
    )

    assert len(trades) == 2
    assert trades[0].quantity == 1
    assert trades[1].quantity == 1


def test_missing_next_minute_skips_entry():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(2, 102, 106, 101, 105),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades == []


def test_closes_at_end_of_data():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert len(trades) == 1
    assert trades[0].exit_reason == "data_end"


def test_closes_at_end_of_day():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(374, 102, 102.5, 101.5, 102),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert trades[0].exit_reason == "end_of_day"


def test_stop_loss_on_entry_minute():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 102, 98, 100),
    ]

    trades = simulate_trades(
        bars,
        [make_signal(bars[0].timestamp)],
        slippage_pct=0,
    )

    assert len(trades) == 1
    assert trades[0].entry_time == bars[1].timestamp
    assert trades[0].exit_time == bars[1].timestamp
    assert trades[0].exit_reason == "stop"
    assert trades[0].exit_price == 99


def test_invalid_starting_cash():
    try:
        simulate_trades([], [], starting_cash=0)
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_invalid_risk_percentage():
    try:
        simulate_trades([], [], risk_per_trade=0)
        assert False, "Expected ValueError"
    except ValueError:
        pass
