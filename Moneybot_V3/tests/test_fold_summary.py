"""Offline descriptive fold summary checks; no broker or network access."""
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.fold_summary import summarize_fixed_baseline_folds
from backtesting.walk_forward import FixedBaselineFoldResult


def fold(number, first, last, pnl, *, signals=2, trades=1, capital=1000):
    return FixedBaselineFoldResult(
        number=number, first_test_date=first, last_test_date=last,
        signal_count=signals, trade_count=trades,
        net_pnl=pnl, return_pct=100 * pnl / capital,
        ending_cash=capital + pnl,
    )


def examples():
    return (
        fold(1, date(2026, 10, 12), date(2026, 10, 13), 20),
        fold(2, date(2026, 10, 14), date(2026, 10, 15), -10),
        fold(3, date(2026, 10, 16), date(2026, 10, 16), 0),
    )


def test_descriptive_fold_summary_never_pools_capital():
    summary = summarize_fixed_baseline_folds(examples())
    assert summary.fold_count == 3
    assert summary.signal_count == 6
    assert summary.trade_count == 3
    assert summary.positive_fold_count == 1
    assert summary.zero_fold_count == 1
    assert summary.mean_fold_return_pct == pytest.approx(1 / 3)
    assert summary.median_fold_return_pct == 0
    assert summary.worst_fold_return_pct == -1
    assert summary.best_fold_return_pct == 2
    assert not hasattr(summary, "total_return_pct")
    assert not hasattr(summary, "pooled_pnl")


def test_summary_supports_explicit_identical_nondefault_starting_capital():
    results = (fold(1, date(2026, 10, 12), date(2026, 10, 13), 50, capital=2000),)
    summary = summarize_fixed_baseline_folds(results, starting_cash=2000)
    assert summary.mean_fold_return_pct == 2.5
    with pytest.raises(ValueError, match="accounting"):
        summarize_fixed_baseline_folds(results)


@pytest.mark.parametrize("bad", [
    (),
    [],
    "not results",
    (object(),),
])
def test_summary_rejects_missing_or_untyped_results(bad):
    with pytest.raises(ValueError):
        summarize_fixed_baseline_folds(bad)


@pytest.mark.parametrize("bad_cash", [0, -1, True, float("nan"), float("inf"), "1000"])
def test_summary_rejects_invalid_capital(bad_cash):
    with pytest.raises(ValueError):
        summarize_fixed_baseline_folds(examples(), starting_cash=bad_cash)


@pytest.mark.parametrize("mutation", [
    lambda r: replace(r, number=0),
    lambda r: replace(r, number=True),
    lambda r: replace(r, signal_count=-1),
    lambda r: replace(r, trade_count=3),
    lambda r: replace(r, trade_count=True),
    lambda r: replace(r, net_pnl=float("nan")),
    lambda r: replace(r, return_pct=float("inf")),
    lambda r: replace(r, ending_cash=-1),
    lambda r: replace(r, ending_cash=r.ending_cash + 1),
    lambda r: replace(r, return_pct=r.return_pct + 1),
    lambda r: replace(r, first_test_date=datetime(2026, 10, 12)),
    lambda r: replace(r, last_test_date=date(2026, 10, 11)),
])
def test_summary_rejects_malformed_fold_results(mutation):
    results = examples()
    with pytest.raises(ValueError):
        summarize_fixed_baseline_folds((mutation(results[0]),) + results[1:])


def test_summary_rejects_reversed_or_overlapping_windows():
    results = examples()
    with pytest.raises(ValueError, match="chronological"):
        summarize_fixed_baseline_folds((results[1], results[0]))
    with pytest.raises(ValueError, match="chronological"):
        summarize_fixed_baseline_folds((results[0], replace(results[1], first_test_date=results[0].last_test_date)))
    with pytest.raises(ValueError, match="numbers"):
        summarize_fixed_baseline_folds((results[0], replace(results[1], number=1)))
