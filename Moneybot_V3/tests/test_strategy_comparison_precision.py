"""Offline precision regressions for comparative paper-trade reporting.

Synthetic closed trades only. No market data, broker, or order submissions.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v3_evaluation import ClosedTrade, compare_paper_strategies, evaluate_closed_trades


def one_trade(pnl):
    return [ClosedTrade(
        "AMD", pnl, "2026-01-02T14:30:00Z", "2026-01-02T14:31:00Z",
    )]


@pytest.mark.parametrize("baseline_pnl, ai_pnl, expected", [
    (0.004, 0.006, 0.00),
    (0.006, 0.014, 0.01),
    (0.014, 0.006, -0.01),
    (9.75, 10.25, 0.50),
])
def test_comparison_rounds_only_after_subtracting_validated_pnl(
    baseline_pnl, ai_pnl, expected,
):
    baseline = one_trade(baseline_pnl)
    ai = one_trade(ai_pnl)
    result = compare_paper_strategies(baseline, ai, 1000.0)

    assert result["ai_minus_baseline_pnl"] == expected
    # The public component reports retain their existing cent rounding.
    assert result["baseline"] == evaluate_closed_trades(baseline, 1000.0)
    assert result["ai"] == evaluate_closed_trades(ai, 1000.0)


def test_comparison_preserves_empty_baseline_and_net_cost_convention():
    result = compare_paper_strategies([], one_trade(-0.01), 1000.0)
    assert result["baseline"]["trade_count"] == 0
    assert result["ai_minus_baseline_pnl"] == -0.01
