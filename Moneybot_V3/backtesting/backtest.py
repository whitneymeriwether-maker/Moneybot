
"""Research-only historical backtester. No broker connections."""

from dataclasses import dataclass
from math import isfinite


def _finite_number(value):
    """Only finite real numeric inputs, never booleans or numeric strings."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class Trade:
    """A completed historical trade, using per-share prices."""
    entry_price: float
    exit_price: float
    quantity: int
    entry_fee: float = 0.0
    exit_fee: float = 0.0


def backtest(trades, starting_cash=1000.0, slippage_pct=0.001):
    """
    Replay completed long trades sequentially.

    Assumes one position at a time, no leverage, and no
    overlapping trades. Slippage applies at entry and exit.
    """
    if not _finite_number(starting_cash) or starting_cash <= 0:
        raise ValueError("Starting cash must be positive")
    if not _finite_number(slippage_pct) or not 0 <= slippage_pct < 1:
        raise ValueError("Invalid slippage")

    cash = starting_cash
    peak = cash
    max_drawdown = 0.0
    wins = 0
    completed = 0
    results = []

    for trade in trades:
        values = (
            trade.entry_price, trade.exit_price,
            trade.entry_fee, trade.exit_fee
        )
        if not all(_finite_number(v) for v in values):
            raise ValueError("Invalid trade value")
        if (trade.entry_price <= 0 or trade.exit_price <= 0
                or type(trade.quantity) is not int
                or trade.quantity <= 0
                or trade.entry_fee < 0 or trade.exit_fee < 0):
            raise ValueError("Invalid trade")

        entry = trade.entry_price * (1 + slippage_pct)
        exit_price = trade.exit_price * (1 - slippage_pct)
        cost = entry * trade.quantity + trade.entry_fee

        if not all(isfinite(v) for v in (entry, exit_price, cost)):
            raise ValueError("Non-finite trade arithmetic")
        if cost > cash:
            raise ValueError("Trade exceeds available cash")

        pnl = (
            (exit_price - entry) * trade.quantity
            - trade.entry_fee - trade.exit_fee
        )
        cash += pnl
        if not isfinite(pnl) or not isfinite(cash):
            raise ValueError("Non-finite trade arithmetic")
        completed += 1
        wins += pnl > 0
        peak = max(peak, cash)
        max_drawdown = max(
            max_drawdown, (peak - cash) / peak
        )
        results.append(round(pnl, 2))

    return {
        "starting_cash": round(starting_cash, 2),
        "ending_cash": round(cash, 2),
        "net_profit": round(cash - starting_cash, 2),
        "return_pct": round(
            100 * (cash / starting_cash - 1), 2
        ),
        "completed_trades": completed,
        "win_rate_pct": round(
            100 * wins / completed, 2
        ) if completed else 0.0,
        "max_closed_trade_drawdown_pct": round(
            100 * max_drawdown, 2
        ),
        "trade_pnl": results,
    }
