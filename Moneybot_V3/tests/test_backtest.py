
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


@pytest.mark.parametrize("parameter,value,expected", [
    ("starting_cash", True, "Starting cash"),
    ("starting_cash", "1000", "Starting cash"),
    ("starting_cash", None, "Starting cash"),
    ("starting_cash", 10 ** 400, "Starting cash"),
    ("slippage_pct", False, "Invalid slippage"),
    ("slippage_pct", "0.001", "Invalid slippage"),
    ("slippage_pct", None, "Invalid slippage"),
])
def test_rejects_malformed_backtest_parameters(parameter, value, expected):
    with pytest.raises(ValueError, match=expected):
        backtest([], **{parameter: value})


@pytest.mark.parametrize("field,value", [
    ("entry_price", True),
    ("exit_price", "12"),
    ("entry_fee", True),
    ("exit_fee", None),
])
def test_rejects_malformed_trade_numbers(field, value):
    values = dict(entry_price=10, exit_price=12, quantity=1, entry_fee=0, exit_fee=0)
    values[field] = value
    with pytest.raises(ValueError, match="Invalid trade value"):
        backtest([Trade(**values)], slippage_pct=0)


def test_rejects_overflowed_backtest_equity():
    with pytest.raises(ValueError, match="Non-finite trade arithmetic"):
        backtest([Trade(entry_price=1, exit_price=1e308, quantity=1)],
                 starting_cash=1e308, slippage_pct=0)
