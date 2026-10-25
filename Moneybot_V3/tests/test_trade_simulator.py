
"""Tests for Moneybot V3's historical trade simulator."""

from datetime import datetime, timedelta
import pytest
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

    assert trades[0].quantity == 4  # 50% of $1,000 at $101/share


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
    assert trades[0].quantity == 1  # 50% of $250 at $101/share


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
        max_exposure=1.0,  # This test isolates cash restoration.
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


def test_session_rollover_uses_last_regular_bar_not_after_hours():
    """An after-hours print must never determine a day-trade exit."""
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(435, 200, 201, 199, 200),  # 5:00 PM
        make_bar(-45, 150, 151, 149, 150, day=13),  # 9:00 AM
    ]
    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == "session_end"
    assert trades[0].exit_time == bars[1].timestamp
    assert trades[0].exit_price == 101


def test_data_end_uses_last_regular_bar_not_after_hours():
    """End-of-file liquidation cannot use extended-hours prices."""
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(435, 200, 201, 199, 200),  # 5:00 PM
    ]
    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == "data_end"
    assert trades[0].exit_time == bars[1].timestamp
    assert trades[0].exit_price == 101


def test_full_exposure_requires_explicit_override():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]
    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)],
        slippage_pct=0, max_exposure=1.0,
    )
    assert len(trades) == 1
    assert trades[0].quantity == 7  # Risk budget binds, not cash.


def test_invalid_exposure_cap_fails_closed():
    for invalid in (0, -0.1, 1.01, True, float("nan"), float("inf"), "0.5"):
        try:
            simulate_trades([], [], max_exposure=invalid)
        except ValueError as exc:
            assert "maximum exposure" in str(exc)
        else:
            raise AssertionError(f"Accepted invalid exposure: {invalid!r}")


def test_simulator_rejects_out_of_order_and_duplicate_bars():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 102, 100, 101),
    ]
    for invalid_bars in (list(reversed(bars)), [bars[0], bars[0]]):
        with pytest.raises(ValueError, match="strictly increasing"):
            simulate_trades(invalid_bars, [], slippage_pct=0)


def test_simulator_rejects_naive_bar_timestamp():
    bar = make_bar(0, 100, 101, 99, 100)
    bar.timestamp = bar.timestamp.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        simulate_trades([bar], [])


@pytest.mark.parametrize("field,value", [
    ("open", float("nan")),
    ("high", float("inf")),
    ("low", 0),
    ("close", True),
    ("close", "100"),
])
def test_simulator_rejects_invalid_bar_prices(field, value):
    bar = make_bar(0, 100, 101, 99, 100)
    setattr(bar, field, value)
    with pytest.raises(ValueError, match="Invalid simulated bar price"):
        simulate_trades([bar], [])


def test_simulator_rejects_inconsistent_ohlc():
    bar = make_bar(0, 100, 101, 99, 100)
    bar.high = 99.5
    with pytest.raises(ValueError, match="Inconsistent simulated OHLC"):
        simulate_trades([bar], [])



@pytest.mark.parametrize("invalid", [
    None,
    "2026-10-12T09:45:00",
    datetime(2026, 10, 12, 9, 45),
])
def test_simulator_rejects_invalid_signal_timestamp(invalid):
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
    ]
    signal = make_signal(invalid)
    with pytest.raises(ValueError, match="Signal timestamp must be timezone-aware"):
        simulate_trades(bars, [signal], slippage_pct=0)


@pytest.mark.parametrize("high,low", [
    (float("nan"), 99.0),
    (float("inf"), 99.0),
    (101.0, float("-inf")),
    (101.0, -1.0),
    (101.0, 0.0),
    (99.0, 99.0),
    (98.0, 99.0),
    (True, 99.0),
    (101.0, "99"),
])
def test_simulator_rejects_invalid_signal_opening_range(high, low):
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
    ]
    signal = make_signal(bars[0].timestamp)
    signal.opening_range_high = high
    signal.opening_range_low = low
    with pytest.raises(ValueError, match="Invalid opening range in signal"):
        simulate_trades(bars, [signal], slippage_pct=0)


def test_simulator_rejects_duplicate_signal_timestamps():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
    ]
    signals = [make_signal(bars[0].timestamp), make_signal(bars[0].timestamp)]
    with pytest.raises(ValueError, match="Duplicate signal timestamp"):
        simulate_trades(bars, signals, slippage_pct=0)


def test_valid_signal_still_simulates_after_validation():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
    ]
    trades = simulate_trades(bars, [make_signal(bars[0].timestamp)], slippage_pct=0)
    assert len(trades) == 1
    assert trades[0].quantity == 4


@pytest.mark.parametrize("invalid", [-1, 1.5, True, None, "1000"])
def test_simulator_rejects_invalid_bar_volume(invalid):
    bar = make_bar(0, 100, 101, 99, 100)
    bar.volume = invalid
    with pytest.raises(ValueError, match="Invalid simulated bar volume"):
        simulate_trades([bar], [])


def test_zero_volume_entry_bar_cannot_fill():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 102, 100, 101),
        make_bar(2, 101, 102, 100, 101),
    ]
    bars[1].volume = 0

    assert simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    ) == []


def test_zero_volume_signal_bar_cannot_trigger_entry():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 102, 100, 101),
    ]
    bars[0].volume = 0

    assert simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    ) == []


def test_zero_volume_bar_cannot_trigger_target_exit():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 101, 110, 100, 101),
        make_bar(3, 101, 102, 100, 101),
    ]
    bars[2].volume = 0

    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    )

    assert len(trades) == 1
    assert trades[0].exit_reason == "data_end"
    assert trades[0].exit_time == bars[3].timestamp
    assert trades[0].exit_price == 101


def test_data_end_uses_last_traded_bar_not_zero_volume_bar():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 200, 201, 199, 200),
    ]
    bars[2].volume = 0

    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    )

    assert len(trades) == 1
    assert trades[0].exit_reason == "data_end"
    assert trades[0].exit_time == bars[1].timestamp
    assert trades[0].exit_price == 101



def test_entry_participation_caps_shares_on_thin_minute():
    """Do not assume a fill larger than 10% of observed minute volume."""
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]
    bars[1].volume = 15

    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    )

    assert len(trades) == 1
    assert trades[0].quantity == 1


def test_entry_skipped_if_participation_allows_no_whole_share():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]
    bars[1].volume = 9

    assert simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    ) == []


def test_participation_limit_can_be_explicitly_tightened():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]
    bars[1].volume = 100

    trades = simulate_trades(
        bars, [make_signal(bars[0].timestamp)],
        slippage_pct=0, max_participation=0.01,
    )
    assert len(trades) == 1
    assert trades[0].quantity == 1


@pytest.mark.parametrize("invalid", [
    0, -0.1, 1.01, True, float("nan"), float("inf"), "0.1",
])
def test_invalid_participation_limit_fails_closed(invalid):
    with pytest.raises(ValueError, match="maximum participation"):
        simulate_trades([], [], max_participation=invalid)


def test_no_entry_if_opening_range_implies_nonpositive_stop():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 101, 101.5, 100.5, 101),
        make_bar(2, 102, 106, 101, 105),
    ]
    signal = make_signal(bars[0].timestamp)
    signal.opening_range_high = 150
    signal.opening_range_low = 1

    assert simulate_trades(bars, [signal], slippage_pct=0) == []


@pytest.mark.parametrize("parameter,value,expected", [
    ("starting_cash", True, "Invalid starting cash"),
    ("starting_cash", "1000", "Invalid starting cash"),
    ("starting_cash", None, "Invalid starting cash"),
    ("starting_cash", 10 ** 400, "Invalid starting cash"),
    ("risk_per_trade", True, "Invalid risk per trade"),
    ("risk_per_trade", "0.015", "Invalid risk per trade"),
    ("risk_per_trade", None, "Invalid risk per trade"),
    ("slippage_pct", False, "Invalid slippage"),
    ("slippage_pct", "0.001", "Invalid slippage"),
    ("slippage_pct", None, "Invalid slippage"),
    ("max_exposure", 10 ** 400, "Invalid maximum exposure"),
    ("max_participation", 10 ** 400, "Invalid maximum participation"),
])
def test_rejects_malformed_simulation_parameters(parameter, value, expected):
    with pytest.raises(ValueError, match=expected):
        simulate_trades([], [], **{parameter: value})


def test_simulator_rejects_oversized_volume_without_overflow():
    bar = make_bar(0, 100, 101, 99, 100)
    bar.volume = 10 ** 400
    with pytest.raises(ValueError, match="Invalid simulated bar volume"):
        simulate_trades([bar], [])


def test_simulator_rejects_nonfinite_entry_from_slippage():
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(1, 1.5e308, 1.5e308, 1.5e308, 1.5e308),
    ]
    with pytest.raises(ValueError, match="Non-finite simulated trade arithmetic"):
        simulate_trades(
            bars, [make_signal(bars[0].timestamp)],
            starting_cash=1e308, slippage_pct=0.5,
        )


def test_simulator_rejects_overflowed_position_sizing():
    bars = [
        make_bar(0, 1e-300, 2e-300, 1e-300, 1.5e-300),
        make_bar(1, 1.5e-300, 1.6e-300, 1.4e-300, 1.5e-300),
    ]
    signal = make_signal(bars[0].timestamp)
    signal.opening_range_high = 1.5e-300
    signal.opening_range_low = 1e-300
    with pytest.raises(ValueError, match="Non-finite simulated trade arithmetic"):
        simulate_trades(
            bars, [signal], starting_cash=1e308, slippage_pct=0,
        )


def test_simulator_rejects_overflowed_exit_proceeds():
    bars = [
        make_bar(0, 1, 2, 1, 1),
        make_bar(1, 1, 1, 1, 1),
        make_bar(2, 1e308, 1e308, 1e308, 1e308),
    ]
    signal = make_signal(bars[0].timestamp)
    signal.opening_range_high = 1.01
    signal.opening_range_low = 1
    with pytest.raises(ValueError, match="Non-finite simulated trade arithmetic"):
        simulate_trades(
            bars, [signal], starting_cash=1e308, slippage_pct=0,
        )


def test_weekend_bars_cannot_fill_direct_paper_signal():
    """Direct simulator callers must not fabricate Sunday equity fills."""
    bars = [
        make_bar(0, 100, 101, 99, 100, day=11),
        make_bar(1, 101, 101.5, 100.5, 101, day=11),
        make_bar(2, 102, 106, 101, 105, day=11),
    ]
    assert bars[0].timestamp.weekday() == 6
    assert simulate_trades(
        bars, [make_signal(bars[0].timestamp)], slippage_pct=0
    ) == []


def test_simulator_rejects_subminute_bar_timestamp():
    bar = make_bar(0, 100, 101, 99, 100)
    bar.timestamp += timedelta(seconds=30)
    with pytest.raises(ValueError, match="Bar timestamp must be minute-aligned"):
        simulate_trades([bar], [])


def test_simulator_rejects_subminute_signal_timestamp():
    bar = make_bar(0, 100, 101, 99, 100)
    signal = make_signal(bar.timestamp + timedelta(seconds=30))
    with pytest.raises(ValueError, match="Signal timestamp must be minute-aligned"):
        simulate_trades([bar], [signal])
