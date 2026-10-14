"""Independent, reproducible evaluation of completed paper trades. No market data fetched."""
from dataclasses import dataclass
from math import sqrt
from statistics import mean

@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    pnl: float             # signed dollars AFTER fees/slippage
    entry_time: str
    exit_time: str


def evaluate_closed_trades(trades: list[ClosedTrade], starting_capital: float) -> dict:
    """Trade-sequence summary, not a substitute for time-based equity backtesting.

    The caller must use point-in-time data and independently model fees,
    slippage, unfilled orders, splits, and overnight gaps.
    """
    if starting_capital <= 0:
        raise ValueError('Starting capital must be positive')
    equity = peak = starting_capital
    max_drawdown = 0.0
    pnls = []
    for trade in trades:
        equity += trade.pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak-equity)/peak)
        pnls.append(trade.pnl)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {
        'trade_count': len(pnls),
        'ending_equity': round(equity, 2),
        'net_pnl': round(sum(pnls), 2),
        'return_pct': round(100 * sum(pnls)/starting_capital, 3),
        'win_rate_pct': round(100*len(wins)/len(pnls), 2) if pnls else None,
        'expectancy_per_trade': round(mean(pnls), 2) if pnls else None,
        'max_closed_trade_drawdown_pct': round(max_drawdown*100, 3),
        'profit_factor': round(sum(wins)/abs(sum(losses)), 3) if losses else None,
    }


def compare_paper_strategies(baseline: list[ClosedTrade], ai: list[ClosedTrade],
                             starting_capital: float) -> dict:
    """Compare strategies using the same capital; does not claim statistical significance."""
    a = evaluate_closed_trades(ai, starting_capital)
    b = evaluate_closed_trades(baseline, starting_capital)
    return {'baseline': b, 'ai': a, 'ai_minus_baseline_pnl': round(a['net_pnl']-b['net_pnl'], 2)}
