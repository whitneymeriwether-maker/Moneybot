"""Reject closed-trade reports whose floating-point cash replay loses PnL."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v3_evaluation import ClosedTrade, evaluate_closed_trades, compare_paper_strategies


def records(*pnls):
    return [
        ClosedTrade(
            "AMD", pnl, f"2026-01-02T14:{30 + index:02d}:00Z",
            f"2026-01-02T14:{31 + index:02d}:00Z",
        )
        for index, pnl in enumerate(pnls)
    ]


def test_rejects_cancellation_that_erases_starting_cash():
    # Incremental float additions lose the $1,000 opening cash, even
    # though the two reported trade PnLs cancel exactly.
    with pytest.raises(ValueError, match="Inconsistent closed-trade cash accounting"):
        evaluate_closed_trades(records(1e20, -1e20), 1000)


def test_rejects_small_profit_swallowed_by_large_cash_balance():
    # $100 is smaller than one ULP at $1e20 and vanishes from cash.
    with pytest.raises(ValueError, match="Inconsistent closed-trade cash accounting"):
        evaluate_closed_trades(records(100), 1e20)


def test_strategy_comparison_rejects_inconsistent_component():
    with pytest.raises(ValueError, match="Inconsistent closed-trade cash accounting"):
        compare_paper_strategies([], records(1e20, -1e20), 1000)


def test_ordinary_cent_level_replay_still_passes():
    result = evaluate_closed_trades(records(0.01, 0.02, -0.03), 1000)
    assert result["net_pnl"] == 0
    assert result["ending_equity"] == 1000
    assert result["trade_count"] == 3
