"""Fail-closed signal provenance checks for offline V3 simulation.

Synthetic minute bars only. No market data requests, brokers, or orders.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backtesting.trade_simulator import simulate_trades


T = datetime(2026, 10, 12, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def bars():
    return [
        SimpleNamespace(timestamp=T, open=101.0, high=102.5,
                        low=100.5, close=102.0, volume=1000),
        SimpleNamespace(timestamp=T + timedelta(minutes=1),
                        open=102.0, high=103.0, low=101.0,
                        close=102.0, volume=1000),
    ]


def signal(**changes):
    values = dict(timestamp=T, opening_range_high=101.0,
                  opening_range_low=99.0, entry_price=102.0, vwap=100.0)
    values.update(changes)
    return SimpleNamespace(**values)


def test_complete_breakout_metadata_reconciles_to_observed_signal_bar():
    trades = simulate_trades(bars(), [signal()], slippage_pct=0)
    assert len(trades) == 1
    assert trades[0].entry_time == T + timedelta(minutes=1)


def test_signal_missing_from_supplied_tape_is_not_silently_ignored():
    missing = signal(timestamp=T + timedelta(minutes=4))
    with pytest.raises(ValueError, match="absent from supplied bars"):
        simulate_trades(bars(), [missing], slippage_pct=0)


def test_timezone_equivalent_signal_timestamp_matches_observed_bar():
    from datetime import timezone
    same_instant = signal(timestamp=T.astimezone(timezone.utc))
    assert len(simulate_trades(bars(), [same_instant], slippage_pct=0)) == 1


@pytest.mark.parametrize("field,value,error", [
    ("entry_price", None, "Invalid signal price/VWAP"),
    ("entry_price", True, "Invalid signal price/VWAP"),
    ("entry_price", float("nan"), "Invalid signal price/VWAP"),
    ("entry_price", float("inf"), "Invalid signal price/VWAP"),
    ("entry_price", 0.0, "Invalid signal price/VWAP"),
    ("vwap", float("nan"), "Invalid signal price/VWAP"),
    ("vwap", 0.0, "Invalid signal price/VWAP"),
    ("entry_price", 103.0, "disagrees with observed bar"),
    ("entry_price", 101.0, "disagrees with observed bar"),
    ("vwap", 102.0, "disagrees with observed bar"),
    ("vwap", 103.0, "disagrees with observed bar"),
])
def test_invalid_or_fabricated_breakout_metadata_fails_closed(field, value, error):
    with pytest.raises(ValueError, match=error):
        simulate_trades(bars(), [signal(**{field: value})], slippage_pct=0)


@pytest.mark.parametrize("missing", ["entry_price", "vwap"])
def test_partially_supplied_signal_metadata_is_rejected(missing):
    candidate = signal()
    delattr(candidate, missing)
    with pytest.raises(ValueError, match="Incomplete signal price/VWAP"):
        simulate_trades(bars(), [candidate], slippage_pct=0)


def test_legacy_direct_call_signal_without_price_metadata_remains_supported():
    legacy = SimpleNamespace(timestamp=T, opening_range_high=101.0,
                             opening_range_low=99.0)
    assert len(simulate_trades(bars(), [legacy], slippage_pct=0)) == 1
