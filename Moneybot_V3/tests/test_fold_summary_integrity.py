"""Fail-closed regression tests for externally constructed V3 fold summaries.

No market data, broker connection, network, or order execution.
"""
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.fold_summary import summarize_fixed_baseline_folds
from backtesting.walk_forward import FixedBaselineFoldResult


def result(*, trades=0, signals=0, pnl=0, first=date(2026, 10, 26),
           last=date(2026, 10, 27)):
    return FixedBaselineFoldResult(
        number=1, first_test_date=first, last_test_date=last,
        signal_count=signals, trade_count=trades, net_pnl=pnl,
        return_pct=pnl / 10, ending_cash=1000 + pnl,
    )


@pytest.mark.parametrize("pnl", [1, -1, 0.01, -0.01])
def test_no_trades_cannot_generate_realized_pnl(pnl):
    with pytest.raises(ValueError, match="without completed trades"):
        summarize_fixed_baseline_folds((result(pnl=pnl),))


def test_no_trades_with_signals_and_zero_return_is_valid():
    summary = summarize_fixed_baseline_folds((result(signals=5),))
    assert summary.signal_count == 5
    assert summary.trade_count == 0
    assert summary.mean_fold_return_pct == 0


def test_no_trades_with_nonzero_return_only_is_rejected():
    with pytest.raises(ValueError, match="without completed trades"):
        summarize_fixed_baseline_folds((replace(result(), return_pct=1),))


def test_traded_fold_may_report_positive_or_negative_pnl():
    for pnl in (-5, 5):
        summary = summarize_fixed_baseline_folds((
            result(trades=1, signals=1, pnl=pnl),
        ))
        assert summary.trade_count == 1
        assert summary.mean_fold_return_pct == pnl / 10


@pytest.mark.parametrize("first,last", [
    (date(2026, 10, 24), date(2026, 10, 26)),
    (date(2026, 10, 26), date(2026, 10, 31)),
    (date(2026, 10, 25), date(2026, 10, 25)),
])
def test_weekend_fold_boundaries_are_not_regular_sessions(first, last):
    with pytest.raises(ValueError, match="weekdays"):
        summarize_fixed_baseline_folds((result(first=first, last=last),))


def test_valid_weekday_fold_boundaries_still_work():
    summary = summarize_fixed_baseline_folds((
        result(first=date(2026, 10, 26), last=date(2026, 10, 27)),
    ))
    assert summary.fold_count == 1



def test_no_trade_cash_drift_is_not_excused_by_accounting_tolerance():
    # A hand-built zero-trade result must not mint even a tiny cash balance.
    forged = replace(result(), ending_cash=1000 + 1e-9)
    with pytest.raises(ValueError, match="without completed trades"):
        summarize_fixed_baseline_folds((forged,))


def test_tolerance_cannot_launder_slightly_insolvent_fold():
    # An ending cash of zero is within the ordinary 1e-8 absolute
    # tolerance of this *negative* expected balance. It is still insolvent.
    forged = replace(
        result(trades=1, signals=1, pnl=-1000.000000001),
        ending_cash=0.0,
    )
    with pytest.raises(ValueError, match="accounting"):
        summarize_fixed_baseline_folds((forged,))


def test_exact_terminal_loss_is_a_valid_final_fold_result():
    summary = summarize_fixed_baseline_folds((
        result(trades=1, signals=1, pnl=-1000),
    ))
    assert summary.worst_fold_return_pct == -100
    assert summary.trade_count == 1


def test_tiny_positive_cash_balance_remains_valid():
    summary = summarize_fixed_baseline_folds((
        result(trades=1, signals=1, pnl=-999.999999999),
    ))
    assert summary.trade_count == 1
    assert summary.worst_fold_return_pct > -100
