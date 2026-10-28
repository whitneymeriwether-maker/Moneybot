
"""Moneybot V3 historical backtesting pipeline.

Research only. Does not connect to a broker or place orders.
"""

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from backtesting.historical_data import load_price_bars
from backtesting.ledger_reconciliation import reconcile_closed_simulation
from backtesting.signals import generate_breakout_signals
from backtesting.trade_simulator import net_trade_profit, simulate_trades


_NEW_YORK = ZoneInfo("America/New_York")


def _finite_report_number(value):
    """Reject non-finite/oversized arithmetic before publishing research PnL."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


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


def validate_traded_regular_minutes(bars):
    """Reject zero-volume regular-session bars in strict research datasets.

    Synthetic price-filled bars can conceal absent trade observations even
    when all 390 expected timestamps are present. This is deliberately
    opt-in: sparse-feed exploratory datasets may contain no-trade minutes.
    """
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        if local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0):
            if bar.volume == 0:
                raise ValueError(
                    "Zero-volume regular-session minute bar: "
                    f"{bar.timestamp.isoformat()}"
                )


def validate_regular_session_coverage(bars):
    """Require observed weekday sessions to span 9:30 through 15:59 NY time.

    This boundary check does not detect entirely absent sessions, exchange
    holidays, early closes, or synthetic zero-volume bars. Pair it with
    the regular-session interior gap check for full-day research data.
    """
    sessions = {}
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        clock = local.time()
        if local.weekday() >= 5 or not (time(9, 30) <= clock < time(16, 0)):
            continue

        day = local.date()
        if day not in sessions:
            sessions[day] = [clock, clock]
        else:
            sessions[day][0] = min(sessions[day][0], clock)
            sessions[day][1] = max(sessions[day][1], clock)

    if not sessions:
        raise ValueError("No regular-session minute bars to validate")

    for day, (first, last) in sessions.items():
        if first != time(9, 30) or last != time(15, 59):
            raise ValueError(
                f"Incomplete regular session on {day}: "
                f"first {first.isoformat()}, last {last.isoformat()}"
            )



def validate_research_window(
    bars, first_session, last_session, minimum_observed_sessions=1,
    closed_sessions=None,
):
    """Validate expected session dates for a research window.

    Without closed_sessions, only endpoints and a coarse session count are
    checked. Supplying an explicit exchange-closure calendar requires every
    other weekday in the span and rejects prints on listed closed days.
    This does not authenticate the calendar or historical market data.
    """
    if (
        type(first_session) is not date
        or type(last_session) is not date
        or first_session > last_session
    ):
        raise ValueError("Invalid expected research session window")
    if (
        type(minimum_observed_sessions) is not int
        or minimum_observed_sessions < 1
    ):
        raise ValueError("Invalid minimum observed sessions")

    if closed_sessions is not None:
        if type(closed_sessions) not in (tuple, list, set, frozenset):
            raise ValueError("Invalid exchange closure calendar")
        if any(
            type(day) is not date
            or day < first_session
            or day > last_session
            or day.weekday() >= 5
            for day in closed_sessions
        ) or len(set(closed_sessions)) != len(closed_sessions):
            raise ValueError("Invalid exchange closure calendar")

    sessions = set()
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        if local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0):
            sessions.add(local.date())

    if not sessions:
        raise ValueError("No regular-session bars in research window")
    if min(sessions) != first_session or max(sessions) != last_session:
        raise ValueError(
            "Historical research window does not match expected session endpoints"
        )
    if len(sessions) < minimum_observed_sessions:
        raise ValueError(
            "Insufficient observed sessions in historical research window: "
            f"{len(sessions)} < {minimum_observed_sessions}"
        )

    if closed_sessions is not None:
        closed = set(closed_sessions)
        expected = set()
        for offset in range((last_session - first_session).days + 1):
            day = first_session + timedelta(days=offset)
            if day.weekday() < 5 and day not in closed:
                expected.add(day)
        if sessions != expected:
            missing = sorted(expected - sessions)
            unexpected = sorted(sessions - expected)
            raise ValueError(
                "Research session calendar mismatch: "
                f"missing {len(missing)} session(s) {missing[:3]}, "
                f"unexpected {len(unexpected)} session(s) {unexpected[:3]}"
            )


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
    paper_ledger_audit: dict | None = None


def run_backtest(
    csv_filename,
    starting_cash=1000.0,
    risk_per_trade=0.015,
    slippage_pct=0.001,
    max_regular_gap_minutes=1,
    require_full_regular_sessions=False,
    require_traded_regular_minutes=False,
    expected_session_span=None,
    minimum_observed_sessions=1,
    closed_sessions=None,
    expected_symbol=None,
    commission_per_share=0.0,
    spread_pct=0.0,
    max_participation=0.10,
    audit_paper_ledger=False,
):
    """Load prices, validate session coverage, and report net-of-cost paper PnL.

    Optional audit replays only cent-exact hypothetical fills in a disposable
    SQLite paper ledger. It is not a fill-verification or broker integration.
    """

    if not _finite_report_number(starting_cash) or starting_cash <= 0:
        raise ValueError("Invalid starting cash for research report")
    if type(audit_paper_ledger) is not bool:
        raise ValueError("Invalid paper-ledger audit requirement")
    if audit_paper_ledger and expected_symbol is None:
        raise ValueError("Paper-ledger audit requires an explicit CSV symbol")
    if type(require_full_regular_sessions) is not bool:
        raise ValueError("Invalid full regular-session requirement")
    if type(require_traded_regular_minutes) is not bool:
        raise ValueError("Invalid traded regular-minute requirement")
    if (
        type(minimum_observed_sessions) is not int
        or minimum_observed_sessions < 1
    ):
        raise ValueError("Invalid minimum observed sessions")
    if expected_session_span is None:
        if minimum_observed_sessions != 1:
            raise ValueError("Minimum observed sessions requires a session span")
        if closed_sessions is not None:
            raise ValueError("Exchange closure calendar requires a session span")
    elif (
        type(expected_session_span) is not tuple
        or len(expected_session_span) != 2
    ):
        raise ValueError("Invalid expected research session window")

    bars = load_price_bars(csv_filename, expected_symbol=expected_symbol)
    validate_regular_session_gaps(bars, max_regular_gap_minutes)
    if require_full_regular_sessions:
        validate_regular_session_coverage(bars)
    if require_traded_regular_minutes:
        validate_traded_regular_minutes(bars)
    if expected_session_span is not None:
        validate_research_window(
            bars, *expected_session_span,
            minimum_observed_sessions=minimum_observed_sessions,
            closed_sessions=closed_sessions,
        )
    signals = generate_breakout_signals(bars)

    trades = simulate_trades(
        bars,
        signals,
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        slippage_pct=slippage_pct,
        commission_per_share=commission_per_share,
        spread_pct=spread_pct,
        max_participation=max_participation,
    )

    # The simulator debits entry and exit fees from its cash balance. Mirror
    # that exact per-trade accounting in ALL report metrics, including win
    # rate and drawdown, instead of reporting gross price-only returns.
    profits = [net_trade_profit(trade) for trade in trades]
    if not all(_finite_report_number(profit) for profit in profits):
        raise ValueError("Non-finite simulated trade profit")

    net_profit = sum(profits)
    ending_cash = starting_cash + net_profit
    return_pct = 100 * net_profit / starting_cash
    if not all(_finite_report_number(value) for value in (
        net_profit, ending_cash, return_pct,
    )):
        raise ValueError("Non-finite research return or equity")
    if ending_cash < 0:
        raise ValueError("Negative cash-funded research equity")

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

    if not all(_finite_report_number(value) for value in (
        average_win, average_loss, gross_profit, gross_loss, profit_factor,
        win_rate_pct,
    )):
        raise ValueError("Non-finite research trade statistics")

    # Calculate drawdown using equity after each closed trade.
    equity = starting_cash
    peak_equity = starting_cash
    maximum_drawdown_pct = 0.0

    for profit in profits:
        equity += profit
        if not _finite_report_number(equity) or equity < 0:
            raise ValueError("Invalid simulated closed-trade equity")
        peak_equity = max(peak_equity, equity)

        drawdown_pct = (
            100 * (peak_equity - equity) / peak_equity
        )
        if not _finite_report_number(drawdown_pct):
            raise ValueError("Non-finite research drawdown")

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

    paper_ledger_audit = None
    if audit_paper_ledger:
        # Opt in only when every hypothetical price and fee is exactly
        # representable in cents; never round slippage-generated fractions.
        # The CSV reader has already bound expected_symbol to every row.
        paper_ledger_audit = reconcile_closed_simulation(
            trades, symbol=expected_symbol, starting_cash=str(starting_cash),
        )
        if (
            abs(Decimal(str(net_profit)) - Decimal(paper_ledger_audit["net_pnl"]))
            > Decimal("0.005")
            or abs(Decimal(str(ending_cash)) - Decimal(paper_ledger_audit["ending_cash"]))
            > Decimal("0.005")
            or paper_ledger_audit["trade_count"] != trade_count
        ):
            raise ValueError("Research report disagrees with audited paper ledger")

    return BacktestReport(
        starting_cash=starting_cash,
        ending_cash=ending_cash,
        net_profit=net_profit,
        return_pct=return_pct,
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
        paper_ledger_audit=paper_ledger_audit,
    )
