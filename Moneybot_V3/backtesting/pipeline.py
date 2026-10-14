
"""Moneybot V3 historical backtesting pipeline.

Research only. Does not connect to a broker or place orders.
"""

from dataclasses import dataclass

from backtesting.historical_data import load_price_bars
from backtesting.signals import generate_breakout_signals
from backtesting.trade_simulator import simulate_trades


@dataclass(frozen=True)
class BacktestReport:
    starting_cash: float
    ending_cash: float
    net_profit: float
    return_pct: float
    trade_count: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    signals: list
    trades: list


def run_backtest(
    csv_filename,
    starting_cash=1000.0,
    risk_per_trade=0.015,
    slippage_pct=0.001,
):
    """Load prices, generate signals, simulate trades and report results."""

    bars = load_price_bars(csv_filename)

    signals = generate_breakout_signals(bars)

    trades = simulate_trades(
        bars,
        signals,
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        slippage_pct=slippage_pct,
    )

    profits = [
        (trade.exit_price - trade.entry_price) * trade.quantity
        for trade in trades
    ]

    net_profit = sum(profits)
    ending_cash = starting_cash + net_profit

    winning_trades = sum(profit > 0 for profit in profits)
    losing_trades = sum(profit < 0 for profit in profits)

    trade_count = len(trades)

    win_rate_pct = (
        100 * winning_trades / trade_count
        if trade_count
        else 0.0
    )

    return BacktestReport(
        starting_cash=starting_cash,
        ending_cash=ending_cash,
        net_profit=net_profit,
        return_pct=100 * net_profit / starting_cash,
        trade_count=trade_count,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=win_rate_pct,
        signals=signals,
        trades=trades,
    )
