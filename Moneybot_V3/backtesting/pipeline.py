
"""Moneybot V3 historical backtesting pipeline.

Research only. Does not connect to a broker or place orders.
"""

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

from backtesting.historical_data import load_price_bars
from backtesting.signals import generate_breakout_signals
from backtesting.trade_simulator import simulate_trades


_NEW_YORK = ZoneInfo("America/New_York")


def validate_regular_session_gaps(bars, max_gap_minutes=1):
    """Reject missing interior regular-session minutes before scoring results.

    This is deliberately conservative for sparse IEX data. It does not
    certify complete sessions, holidays, corporate actions, or provenance.
    """
    if type(max_gap_minutes) is not int or max_gap_minutes < 1:
        raise ValueError("Invalid maximum regular-session gap")

    previous_regular = None
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        if local.weekday() >= 5 or not (time(9, 30) <= local.time() < time(16, 0)):
            continue
        if previous_regular is not None:
            previous_local = previous_regular.timestamp.astimezone(_NEW_YORK)
            if previous_local.date() == local.date():
                gap_minutes = (bar.timestamp - previous_regular.timestamp).total_seconds() / 60
                if gap_minutes > max_gap_minutes:
                    raise ValueError(
                        "Missing regular-session minute bars: "
                        f"{previous_regular.timestamp.isoformat()} to "
                        f"{bar.timestamp.isoformat()}"
                    )
        previous_regular = bar


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

    average_win: float = 0.0
    average_loss: float = 0.0
    profit_factor: float = 0.0
    maximum_drawdown_pct: float = 0.0
    stop_loss_exits: int = 0
    target_exits: int = 0
    end_of_day_exits: int = 0


def run_backtest(
    csv_filename,
    starting_cash=1000.0,
    risk_per_trade=0.015,
    slippage_pct=0.001,
    max_regular_gap_minutes=1,
):
    """Load prices, reject interior regular-session gaps, then simulate."""

    bars = load_price_bars(csv_filename)
    validate_regular_session_gaps(bars, max_regular_gap_minutes)
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

    wins = [profit for profit in profits if profit > 0]
    losses = [profit for profit in profits if profit < 0]

    winning_trades = len(wins)
    losing_trades = len(losses)
    trade_count = len(trades)

    win_rate_pct = (
        100 * winning_trades / trade_count
        if trade_count
        else 0.0
    )

    average_win = (
        sum(wins) / len(wins)
        if wins
        else 0.0
    )

    average_loss = (
        sum(losses) / len(losses)
        if losses
        else 0.0
    )

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else 0.0
    )

    # Calculate drawdown using equity after each closed trade.
    equity = starting_cash
    peak_equity = starting_cash
    maximum_drawdown_pct = 0.0

    for profit in profits:
        equity += profit
        peak_equity = max(peak_equity, equity)

        drawdown_pct = (
            100 * (peak_equity - equity) / peak_equity
        )

        maximum_drawdown_pct = max(
            maximum_drawdown_pct,
            drawdown_pct,
        )

    stop_loss_exits = sum(
        trade.exit_reason == "stop"
        for trade in trades
    )

    target_exits = sum(
        trade.exit_reason == "target"
        for trade in trades
    )

    end_of_day_exits = sum(
        trade.exit_reason in (
            "end_of_day",
            "session_end",
            "data_end",
        )
        for trade in trades
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
        average_win=average_win,
        average_loss=average_loss,
        profit_factor=profit_factor,
        maximum_drawdown_pct=maximum_drawdown_pct,
        stop_loss_exits=stop_loss_exits,
        target_exits=target_exits,
        end_of_day_exits=end_of_day_exits,
    )
