"""Offline regressions for UTC-aligned fold construction and report arithmetic.

These tests use synthetic minute bars and mocked paper trades only.
No providers, brokerage connections, or order submissions.
"""

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.trade_simulator import SimulatedTrade
from backtesting.walk_forward import build_research_folds, evaluate_fixed_baseline_folds


def _bars(offset=timedelta(hours=-4)):
    tz = timezone(offset)
    day = date(2026, 10, 12)
    bars = []
    for _ in range(6):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        start = datetime.combine(day, time(9, 30), tzinfo=tz)
        for minute in range(390):
            bars.append(SimpleNamespace(
                timestamp=start + timedelta(minutes=minute),
                open=100.0, high=101.0, low=99.0, close=100.0,
                volume=1000,
            ))
        day += timedelta(days=1)
    return bars


@pytest.mark.parametrize("offset", [
    timedelta(hours=-4, seconds=30),
    timedelta(hours=-4, seconds=-30),
])
def test_fold_builder_rejects_local_minute_with_nonminute_utc_instant(offset):
    # Local timestamps all display :00 seconds, but their UTC instants
    # fall at :30 seconds. Reject before session coverage or scoring.
    with pytest.raises(ValueError, match="Invalid or nonchronological research timestamp"):
        build_research_folds(
            _bars(offset), train_sessions=3, embargo_sessions=1, test_sessions=2
        )


def test_fold_builder_accepts_exact_utc_minute_offset():
    folds = build_research_folds(
        _bars(), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    assert len(folds) == 1
    assert len(folds[0].test_bars) == 780


@pytest.mark.parametrize("starting_cash,exit_price", [
    (1e-320, 101.0),  # Finite net PnL but overflowing percentage return.
    (1000.0, 0.01),   # This synthetic result would exhaust the account below zero.
])
def test_fold_evaluator_rejects_invalid_accounting_at_report_boundary(
    monkeypatch, starting_cash, exit_price,
):
    fold, = build_research_folds(
        _bars(), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    monkeypatch.setattr(
        "backtesting.walk_forward.generate_breakout_signals", lambda bars: []
    )

    def fake_simulate(bars, signals, **kwargs):
        return [SimulatedTrade(
            entry_time=fold.test_bars[0].timestamp,
            exit_time=fold.test_bars[1].timestamp,
            entry_price=100.0, exit_price=exit_price,
            quantity=11 if starting_cash == 1000.0 else 1,
            exit_reason="stop",
        )]

    monkeypatch.setattr("backtesting.walk_forward.simulate_trades", fake_simulate)
    with pytest.raises(ValueError, match="Invalid fixed-baseline fold accounting"):
        evaluate_fixed_baseline_folds((fold,), starting_cash=starting_cash)


def test_fold_evaluator_retains_valid_finite_paper_result(monkeypatch):
    fold, = build_research_folds(
        _bars(), train_sessions=3, embargo_sessions=1, test_sessions=2
    )
    monkeypatch.setattr(
        "backtesting.walk_forward.generate_breakout_signals", lambda bars: []
    )
    monkeypatch.setattr(
        "backtesting.walk_forward.simulate_trades",
        lambda bars, signals, **kwargs: [SimulatedTrade(
            entry_time=fold.test_bars[0].timestamp,
            exit_time=fold.test_bars[1].timestamp,
            entry_price=100.0, exit_price=101.0,
            quantity=1, exit_reason="target",
        )],
    )
    result, = evaluate_fixed_baseline_folds((fold,), starting_cash=1000.0)
    assert result.net_pnl == 1.0
    assert result.ending_cash == 1001.0
    assert result.return_pct == 0.1
