"""Independent, reproducible evaluation of completed paper trades. No market data fetched."""
from dataclasses import dataclass
from math import isfinite
from statistics import mean


def _finite_number(value):
    """Reject booleans, malformed numbers, and integers too large for float."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


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
    if not _finite_number(starting_capital) or starting_capital <= 0:
        raise ValueError('Starting capital must be finite and positive')
    equity = peak = starting_capital
    max_drawdown = 0.0
    pnls = []
    for trade in trades:
        if not _finite_number(trade.pnl):
            raise ValueError('Trade PnL must be a finite number')
        equity += trade.pnl
        if not isfinite(equity):
            raise ValueError('Non-finite cumulative equity')
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        if not isfinite(drawdown):
            raise ValueError('Non-finite closed-trade drawdown')
        max_drawdown = max(max_drawdown, drawdown)
        pnls.append(trade.pnl)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net_pnl = sum(pnls)
    gross_wins = sum(wins)
    gross_losses = sum(losses)
    if not all(isfinite(value) for value in (net_pnl, gross_wins, gross_losses)):
        raise ValueError('Non-finite aggregate PnL')
    profit_factor = gross_wins / abs(gross_losses) if losses else None
    if profit_factor is not None and not isfinite(profit_factor):
        raise ValueError('Non-finite profit factor')
    return_pct = (net_pnl / starting_capital) * 100
    if not isfinite(return_pct):
        raise ValueError('Non-finite return percentage')
    return {
        'trade_count': len(pnls),
        'ending_equity': round(equity, 2),
        'net_pnl': round(net_pnl, 2),
        'return_pct': round(return_pct, 3),
        'win_rate_pct': round(100*len(wins)/len(pnls), 2) if pnls else None,
        'expectancy_per_trade': round(mean(pnls), 2) if pnls else None,
        'max_closed_trade_drawdown_pct': round(max_drawdown*100, 3),
        'profit_factor': round(profit_factor, 3) if losses else None,
    }


def compare_paper_strategies(baseline: list[ClosedTrade], ai: list[ClosedTrade],
                             starting_capital: float) -> dict:
    """Compare strategies using the same capital; does not claim statistical significance."""
    a = evaluate_closed_trades(ai, starting_capital)
    b = evaluate_closed_trades(baseline, starting_capital)
    return {'baseline': b, 'ai': a, 'ai_minus_baseline_pnl': round(a['net_pnl']-b['net_pnl'], 2)}
