"""Offline provenance regression tests for complete opening-range signals.

No network requests, brokerage access, or live orders.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backtesting.historical_data import PriceBar
from backtesting.signals import generate_breakout_signals
from backtesting.trade_simulator import simulate_trades


NY = ZoneInfo("America/New_York")
START = datetime(2026, 10, 12, 9, 30, tzinfo=NY)


def complete_tape(*, breakout=True):
    bars = [
        PriceBar(START + timedelta(minutes=minute),
                 100.0, 101.0, 99.0, 100.0, 1000)
        for minute in range(15)
    ]
    close = 102.0 if breakout else 100.5
    bars.append(PriceBar(START + timedelta(minutes=15),
                         close, close + 0.5, close - 0.5, close, 1000))
    bars.append(PriceBar(START + timedelta(minutes=16),
                         102.0, 103.0, 101.0, 102.0, 1000))
    return bars


def test_complete_scanner_signal_reconciles_and_trades():
    bars = complete_tape()
    signals = generate_breakout_signals(bars)
    assert len(signals) == 1
    trades = simulate_trades(bars, signals, slippage_pct=0)
    assert len(trades) == 1
    assert trades[0].entry_time == bars[-1].timestamp


@pytest.mark.parametrize("change", [
    {"opening_range_high": 100.5},
    {"opening_range_low": 98.0},
    {"vwap": 99.0},
    {"vwap": 101.0},
])
def test_fabricated_range_or_vwap_is_rejected(change):
    bars = complete_tape()
    signal = replace(generate_breakout_signals(bars)[0], **change)
    with pytest.raises(ValueError, match="opening range/VWAP"):
        simulate_trades(bars, [signal], slippage_pct=0)


def test_fabricated_breakout_rejected_when_scanner_saw_none():
    bars = complete_tape(breakout=False)
    assert all(s.timestamp != bars[15].timestamp for s in generate_breakout_signals(bars))
    from backtesting.signals import BreakoutSignal
    fake = BreakoutSignal(
        timestamp=bars[15].timestamp,
        entry_price=100.5,
        opening_range_high=100.0,
        opening_range_low=99.0,
        vwap=100.0,
    )
    with pytest.raises(ValueError, match="opening range/VWAP"):
        simulate_trades(bars, [fake], slippage_pct=0)


def test_timezone_equivalent_complete_signal_still_reconciles():
    bars = complete_tape()
    signal = generate_breakout_signals(bars)[0]
    signal = replace(signal, timestamp=signal.timestamp.astimezone(timezone.utc))
    assert len(simulate_trades(bars, [signal], slippage_pct=0)) == 1


def test_short_legacy_tape_does_not_require_missing_opening_range():
    bars = complete_tape()[15:]
    signal = generate_breakout_signals(complete_tape())[0]
    assert len(simulate_trades(bars, [signal], slippage_pct=0)) == 1


def test_complete_range_cannot_bypass_provenance_by_omitting_metadata():
    from types import SimpleNamespace

    bars = complete_tape()
    expected = generate_breakout_signals(bars)[0]
    legacy = SimpleNamespace(
        timestamp=expected.timestamp,
        opening_range_high=expected.opening_range_high,
        opening_range_low=expected.opening_range_low,
    )
    with pytest.raises(ValueError, match="requires signal price/VWAP"):
        simulate_trades(bars, [legacy], slippage_pct=0)


def test_complete_nonbreakout_tape_rejects_legacy_fabricated_signal():
    from types import SimpleNamespace

    bars = complete_tape(breakout=False)
    fabricated = SimpleNamespace(
        timestamp=bars[15].timestamp,
        opening_range_high=100.0,
        opening_range_low=99.0,
    )
    with pytest.raises(ValueError, match="requires signal price/VWAP"):
        simulate_trades(bars, [fabricated], slippage_pct=0)


def test_short_tape_still_supports_genuine_legacy_signal_without_metadata():
    from types import SimpleNamespace

    full = complete_tape()
    expected = generate_breakout_signals(full)[0]
    legacy = SimpleNamespace(
        timestamp=expected.timestamp,
        opening_range_high=expected.opening_range_high,
        opening_range_low=expected.opening_range_low,
    )
    assert len(simulate_trades(full[15:], [legacy], slippage_pct=0)) == 1
