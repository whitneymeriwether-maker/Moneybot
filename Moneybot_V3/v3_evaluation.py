"""Independent, reproducible evaluation of completed paper trades. No market data fetched."""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import fsum, isfinite
import re
from statistics import mean


# Explicit offset and second precision are mandatory. Restrict fractions to
# microseconds so Python cannot silently truncate ordering information.
_RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def _trade_instant(value):
    """Parse an explicit-offset RFC 3339 timestamp without lossy precision."""
    if type(value) is not str or _RFC3339.fullmatch(value) is None:
        raise ValueError("Invalid closed trade timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except (ValueError, OverflowError):
        raise ValueError("Invalid closed trade timestamp") from None


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
    if type(trades) not in (list, tuple):
        raise ValueError('Closed trades must be a list or tuple')
    equity = peak = starting_capital
    max_drawdown = 0.0
    pnls = []
    previous_exit = None
    for trade in trades:
        if not isinstance(trade, ClosedTrade):
            raise ValueError('Invalid closed trade record')
        if type(trade.symbol) is not str or _SYMBOL.fullmatch(trade.symbol) is None:
            raise ValueError('Invalid closed trade symbol')
        entry = _trade_instant(trade.entry_time)
        exit_at = _trade_instant(trade.exit_time)
        if exit_at <= entry:
            raise ValueError('Closed trade exit must follow entry')
        # A cash-only replay is sensitive to realized PnL ordering. Do not
        # allow a caller to reorder winners ahead of earlier losses, or to
        # choose an arbitrary ordering for simultaneous closes.
        if previous_exit is not None and exit_at <= previous_exit:
            raise ValueError('Closed trades require strictly increasing exits')
        # Once a cash-only account reaches zero, another completed trade
        # cannot be funded, even if its reported PnL is zero or positive.
        if equity == 0:
            raise ValueError('Closed trade after cash-funded account depletion')
        # This evaluator has no entry notionals or reserved-cash history.
        # It can verify a sequential cash-funded replay, but cannot prove
        # that overlapping positions were funded. Fail closed rather than
        # presenting an unverified portfolio drawdown or return.
        if previous_exit is not None and entry < previous_exit:
            raise ValueError('Closed trades overlap in cash-only evaluation')
        previous_exit = exit_at
        if not _finite_number(trade.pnl):
            raise ValueError('Trade PnL must be a finite number')
        equity += trade.pnl
        if not isfinite(equity):
            raise ValueError('Non-finite cumulative equity')
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak
        if not isfinite(drawdown):
            raise ValueError('Non-finite closed-trade drawdown')
        # A cash-funded paper account cannot continue after insolvency.
        # Reject even if a later hypothetical win would restore equity.
        if equity < 0:
            raise ValueError('Negative cash-funded closed-trade equity')
        max_drawdown = max(max_drawdown, drawdown)
        pnls.append(trade.pnl)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    # Use compensated summation so cancellation does not conceal PnL that
    # sequential floating-point cash updates may have silently lost.
    try:
        net_pnl = fsum(pnls)
    except (OverflowError, ValueError):
        raise ValueError('Non-finite aggregate PnL') from None
    gross_wins = sum(wins)
    gross_losses = sum(losses)
    if not all(isfinite(value) for value in (net_pnl, gross_wins, gross_losses)):
        raise ValueError('Non-finite aggregate PnL')
    # This is a cash-funded replay. A rounded cash balance that disagrees
    # with the realized trade PnL by more than half a cent is not a credible
    # performance result. Reject it instead of presenting contradictory
    # ending equity and return numbers.
    realized_change = equity - starting_capital
    if (not isfinite(realized_change)
            or abs(realized_change - net_pnl) > 0.005):
        raise ValueError('Inconsistent closed-trade cash accounting')
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
