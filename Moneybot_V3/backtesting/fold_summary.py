"""Descriptive summaries of independent, non-overlapping V3 paper research folds.

This module never pools fold capital or treats fold outcomes as independent
statistical trials. It performs no data retrieval, broker operations or orders.
"""
from dataclasses import dataclass
from datetime import date
from math import isclose, isfinite
from statistics import mean, median

from backtesting.walk_forward import FixedBaselineFoldResult


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


@dataclass(frozen=True)
class FixedBaselineSummary:
    fold_count: int
    signal_count: int
    trade_count: int
    positive_fold_count: int
    zero_fold_count: int
    mean_fold_return_pct: float
    median_fold_return_pct: float
    worst_fold_return_pct: float
    best_fold_return_pct: float


def summarize_fixed_baseline_folds(results, *, starting_cash=1000.0):
    """Summarize disjoint chronological out-of-sample test windows.

    Each fold is independently restarted with the SAME starting cash. This
    intentionally does not return a pooled PnL, compounded return, confidence
    interval or Sharpe ratio. Overlapping or reversed test windows, inconsistent
    accounting, and malformed result records fail closed. A valid summary is
    descriptive only; it cannot establish profitable out-of-sample performance.
    """
    if type(results) not in (tuple, list) or not results:
        raise ValueError("At least one completed baseline fold is required")
    if (
        not _finite_number(starting_cash) or starting_cash <= 0
    ):
        raise ValueError("Invalid research starting cash")

    previous_number = 0
    previous_end = None
    returns = []
    signals = trades = 0
    for result in results:
        if not isinstance(result, FixedBaselineFoldResult):
            raise ValueError("Invalid baseline fold result")
        if type(result.number) is not int or result.number <= previous_number:
            raise ValueError("Baseline fold numbers must increase")
        if (
            type(result.first_test_date) is not date
            or type(result.last_test_date) is not date
            or result.first_test_date > result.last_test_date
            or (previous_end is not None and result.first_test_date <= previous_end)
        ):
            raise ValueError("Baseline test windows must be chronological and disjoint")
        if (
            type(result.signal_count) is not int
            or type(result.trade_count) is not int
            or result.signal_count < 0
            or not 0 <= result.trade_count <= result.signal_count
        ):
            raise ValueError("Invalid baseline signal/trade counts")
        values = (result.net_pnl, result.return_pct, result.ending_cash)
        if not all(_finite_number(v) for v in values):
            raise ValueError("Non-finite baseline fold result")
        if result.ending_cash < 0:
            raise ValueError("Negative baseline ending cash")
        expected_cash = starting_cash + result.net_pnl
        expected_return = 100 * result.net_pnl / starting_cash
        if (
            not _finite_number(expected_cash) or not _finite_number(expected_return)
            or not isclose(result.ending_cash, expected_cash, rel_tol=1e-9, abs_tol=1e-8)
            or not isclose(result.return_pct, expected_return, rel_tol=1e-9, abs_tol=1e-8)
        ):
            raise ValueError("Inconsistent baseline fold accounting")
        previous_number = result.number
        previous_end = result.last_test_date
        returns.append(result.return_pct)
        signals += result.signal_count
        trades += result.trade_count

    try:
        mean_return = mean(returns)
        median_return = median(returns)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Non-finite aggregate fold return") from exc
    if not _finite_number(mean_return) or not _finite_number(median_return):
        raise ValueError("Non-finite aggregate fold return")

    return FixedBaselineSummary(
        fold_count=len(returns),
        signal_count=signals,
        trade_count=trades,
        positive_fold_count=sum(r > 0 for r in returns),
        zero_fold_count=sum(r == 0 for r in returns),
        mean_fold_return_pct=mean_return,
        median_fold_return_pct=median_return,
        worst_fold_return_pct=min(returns),
        best_fold_return_pct=max(returns),
    )
