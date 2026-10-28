"""Regression checks for cash-funded trade replay after account depletion."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.backtest import Trade, backtest
from v3_evaluation import ClosedTrade, evaluate_closed_trades, compare_paper_strategies


def closed(pnl):
    return ClosedTrade("AMD", pnl, "entry", "exit")


@pytest.mark.parametrize("later_pnl", [0, 100, -1])
def test_completed_trade_evaluator_rejects_trade_after_total_loss(later_pnl):
    with pytest.raises(ValueError, match="after cash-funded account depletion"):
        evaluate_closed_trades([closed(-1000), closed(later_pnl)], 1000)


@pytest.mark.parametrize("side", ["ai", "baseline"])
def test_strategy_comparison_rejects_post_depletion_trade(side):
    invalid = [closed(-1000), closed(100)]
    ai = invalid if side == "ai" else []
    baseline = invalid if side == "baseline" else []
    with pytest.raises(ValueError, match="after cash-funded account depletion"):
        compare_paper_strategies(baseline, ai, 1000)


def test_backtest_rejects_second_trade_after_exact_total_loss():
    trades = [Trade(10, 1, 1, exit_fee=991), Trade(10, 20, 1)]
    with pytest.raises(ValueError, match="after cash-funded account depletion"):
        backtest(trades, starting_cash=1000, slippage_pct=0)


@pytest.mark.parametrize("bad", [None, {"pnl": 1}, object()])
def test_completed_trade_evaluator_rejects_malformed_record(bad):
    with pytest.raises(ValueError, match="Invalid closed trade record"):
        evaluate_closed_trades([bad], 1000)


@pytest.mark.parametrize("bad", [None, {"entry_price": 10}, object()])
def test_backtest_rejects_malformed_record(bad):
    with pytest.raises(ValueError, match="Invalid completed trade record"):
        backtest([bad], starting_cash=1000, slippage_pct=0)


def test_exact_total_loss_as_final_trade_remains_reportable():
    assert evaluate_closed_trades([closed(-1000)], 1000)["ending_equity"] == 0
    assert backtest([Trade(10, 1, 1, exit_fee=991)],
                    starting_cash=1000, slippage_pct=0)["ending_cash"] == 0
