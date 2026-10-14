
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.backtest import Trade, backtest


def test_profitable_trade():
    result = backtest(
        [Trade(entry_price=10, exit_price=12, quantity=10)],
        slippage_pct=0
    )
    assert result["ending_cash"] == 1020.0
    assert result["net_profit"] == 20.0
    assert result["win_rate_pct"] == 100.0


def test_losing_trade():
    result = backtest(
        [Trade(entry_price=10, exit_price=9, quantity=10)],
        slippage_pct=0
    )
    assert result["ending_cash"] == 990.0
    assert result["win_rate_pct"] == 0.0
    assert result["max_closed_trade_drawdown_pct"] == 1.0


def test_trading_fees():
    result = backtest(
        [Trade(10, 11, 10, entry_fee=1, exit_fee=1)],
        slippage_pct=0
    )
    assert result["net_profit"] == 8.0


def test_slippage_reduces_profit():
    trade = [Trade(10, 11, 10)]
    without_slippage = backtest(trade, slippage_pct=0)
    with_slippage = backtest(trade, slippage_pct=0.001)
    assert with_slippage["net_profit"] < without_slippage["net_profit"]


def test_insufficient_cash_rejected():
    with pytest.raises(ValueError):
        backtest([Trade(100, 110, 20)])


def test_empty_history():
    result = backtest([])
    assert result["ending_cash"] == 1000.0
    assert result["completed_trades"] == 0


def test_invalid_trade_rejected():
    with pytest.raises(ValueError):
        backtest([Trade(10, 11, -5)])
