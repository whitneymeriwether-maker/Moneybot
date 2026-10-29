"""Research fold accounting tolerances must not conceal material cash drift."""
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.fold_summary import summarize_fixed_baseline_folds
from backtesting.walk_forward import FixedBaselineFoldResult


def _fold(capital=1_000_000_000_000.0, pnl=100.0):
    return FixedBaselineFoldResult(
        number=1,
        first_test_date=date(2026, 10, 26),
        last_test_date=date(2026, 10, 27),
        signal_count=1,
        trade_count=1,
        net_pnl=pnl,
        return_pct=100 * pnl / capital,
        ending_cash=capital + pnl,
    )


def test_large_research_balance_does_not_hide_hundred_dollar_cash_drift():
    capital = 1_000_000_000_000.0
    forged = replace(_fold(), ending_cash=capital + 200.0)
    with pytest.raises(ValueError, match="accounting"):
        summarize_fixed_baseline_folds((forged,), starting_cash=capital)


def test_large_research_balance_does_not_hide_return_misstatement():
    capital = 1_000_000_000_000.0
    original = _fold()
    # 5e-10 percentage points represents $5 on this capital.
    forged = replace(original, return_pct=original.return_pct + 5e-10)
    with pytest.raises(ValueError, match="accounting"):
        summarize_fixed_baseline_folds((forged,), starting_cash=capital)


def test_exact_large_balance_fold_still_summarizes():
    summary = summarize_fixed_baseline_folds(
        (_fold(),), starting_cash=1_000_000_000_000.0,
    )
    assert summary.fold_count == 1
    assert summary.trade_count == 1


def test_tiny_ordinary_float_reporting_drift_is_still_tolerated():
    capital = 1000.0
    original = _fold(capital=capital, pnl=1.0)
    drifted = replace(
        original,
        ending_cash=original.ending_cash + 1e-7,
        return_pct=original.return_pct + 1e-9,
    )
    summary = summarize_fixed_baseline_folds((drifted,), starting_cash=capital)
    assert summary.fold_count == 1


def test_half_cent_cap_rejects_even_when_relative_tolerance_would_pass():
    capital = 1_000_000_000_000.0
    original = _fold()
    forged = replace(original, ending_cash=original.ending_cash + 0.01)
    with pytest.raises(ValueError, match="accounting"):
        summarize_fixed_baseline_folds((forged,), starting_cash=capital)
