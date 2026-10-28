"""Regression tests for closed-trade insolvency in offline cash-only research."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.backtest import Trade, backtest
from v3_evaluation import ClosedTrade, compare_paper_strategies, evaluate_closed_trades


def closed(pnl, index=0):
    return ClosedTrade(
        "AMD", pnl, "2026-01-02T14:30:00Z",
        f"2026-01-02T14:{31 + index:02d}:00Z",
    )


@pytest.mark.parametrize("pnls", [
    [-1000.01],
    [-1100.0, 1200.0],
])
def test_closed_trade_evaluator_rejects_insolvency_even_if_recovered(pnls):
    with pytest.raises(ValueError, match="Negative cash-funded closed-trade equity"):
        evaluate_closed_trades([closed(pnl, i) for i, pnl in enumerate(pnls)], 1000)


def test_closed_trade_evaluator_allows_exact_total_loss():
    result = evaluate_closed_trades([closed(-1000.0)], 1000)
    assert result["ending_equity"] == 0
    assert result["max_closed_trade_drawdown_pct"] == 100


@pytest.mark.parametrize("insolvent_side", ["baseline", "ai"])
def test_strategy_comparison_rejects_insolvent_sequence(insolvent_side):
    trades = [closed(-1001.0)]
    baseline = trades if insolvent_side == "baseline" else []
    ai = trades if insolvent_side == "ai" else []
    with pytest.raises(ValueError, match="Negative cash-funded closed-trade equity"):
        compare_paper_strategies(baseline, ai, 1000)


@pytest.mark.parametrize("trades", [
    [Trade(10, 1, 1, exit_fee=1000)],
    [Trade(10, 1, 1, exit_fee=1000), Trade(10, 20, 1)],
])
def test_sequential_backtest_rejects_insolvency_even_if_recovered(trades):
    with pytest.raises(ValueError, match="Negative cash-funded backtest equity"):
        backtest(trades, starting_cash=1000, slippage_pct=0)


def test_sequential_backtest_allows_exact_total_loss():
    result = backtest(
        [Trade(10, 1, 1, exit_fee=991)], starting_cash=1000, slippage_pct=0,
    )
    assert result["ending_cash"] == 0
    assert result["max_closed_trade_drawdown_pct"] == 100
