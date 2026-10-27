"""Leakage-resistant chronological research folds for offline V3 baseline studies.

These folds separate training, embargo, and test sessions. No model is trained
here; the optional fixed-strategy evaluator scores only the test bars. This
does not establish point-in-time data provenance or profitable performance.
There are no broker, network, or order-submission operations.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from backtesting.pipeline import (
    validate_regular_session_coverage,
    validate_regular_session_gaps,
    validate_research_window,
)
from backtesting.signals import generate_breakout_signals
from backtesting.trade_simulator import simulate_trades


_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ResearchFold:
    number: int
    train_dates: tuple
    embargo_dates: tuple
    test_dates: tuple
    train_bars: tuple
    test_bars: tuple


@dataclass(frozen=True)
class FixedBaselineFoldResult:
    number: int
    first_test_date: date
    last_test_date: date
    signal_count: int
    trade_count: int
    net_pnl: float
    return_pct: float
    ending_cash: float


def build_research_folds(
    bars, *, train_sessions, test_sessions, embargo_sessions=1,
    step_sessions=None, expected_session_span=None, closed_sessions=None,
):
    """Create non-overlapping out-of-sample windows from full NYSE sessions.

    Each observed session must contain all 390 consecutive, traded regular
    minutes with valid OHLCV. A supplied calendar additionally detects entire
    missing sessions; without it, absent dates cannot be distinguished from
    market holidays. This intentionally rejects early-close sessions.
    Test windows never overlap and never contain training/embargo bars.
    """
    if (
        type(train_sessions) is not int or train_sessions < 1
        or type(test_sessions) is not int or test_sessions < 1
        or type(embargo_sessions) is not int or embargo_sessions < 0
    ):
        raise ValueError("Invalid research fold session counts")
    if step_sessions is None:
        step_sessions = test_sessions
    if type(step_sessions) is not int or step_sessions < test_sessions:
        raise ValueError("Step must prevent overlapping test windows")
    if expected_session_span is None:
        if closed_sessions is not None:
            raise ValueError("Closure calendar requires an expected session span")
    elif (
        type(expected_session_span) is not tuple
        or len(expected_session_span) != 2
    ):
        raise ValueError("Invalid expected session span")

    bars = tuple(bars)
    if not bars:
        raise ValueError("No historical bars to split")
    sessions = {}
    previous = None
    for bar in bars:
        stamp = getattr(bar, "timestamp", None)
        if (
            not isinstance(stamp, datetime)
            or stamp.tzinfo is None or stamp.utcoffset() is None
            or stamp.second != 0 or stamp.microsecond != 0
            or (previous is not None and stamp <= previous)
        ):
            raise ValueError("Invalid or nonchronological research timestamp")
        previous = stamp
        local = stamp.astimezone(_NEW_YORK)
        if local.weekday() >= 5 or not time(9, 30) <= local.time() < time(16, 0):
            raise ValueError("Research folds require regular weekday minutes only")
        prices = tuple(getattr(bar, key, None) for key in ("open", "high", "low", "close"))
        if any(
            type(price) not in (int, float) or not isfinite(price) or price <= 0
            for price in prices
        ):
            raise ValueError("Invalid research OHLC price")
        opening, high, low, close = prices
        if high < max(opening, low, close) or low > min(opening, high, close):
            raise ValueError("Inconsistent research OHLC bar")
        volume = getattr(bar, "volume", None)
        if type(volume) is not int or volume <= 0:
            raise ValueError("Research folds require traded minute volumes")
        sessions.setdefault(local.date(), []).append(bar)

    validate_regular_session_gaps(bars)
    validate_regular_session_coverage(bars)
    if any(len(day_bars) != 390 for day_bars in sessions.values()):
        raise ValueError("Research folds require 390 minute bars per session")
    if expected_session_span is not None:
        validate_research_window(
            bars, *expected_session_span, closed_sessions=closed_sessions
        )

    dates = tuple(sessions)
    required = train_sessions + embargo_sessions + test_sessions
    if len(dates) < required:
        raise ValueError("Insufficient sessions for a complete research fold")

    folds = []
    for start in range(0, len(dates) - required + 1, step_sessions):
        train_dates = dates[start:start + train_sessions]
        embargo_dates = dates[
            start + train_sessions:start + train_sessions + embargo_sessions
        ]
        test_dates = dates[
            start + train_sessions + embargo_sessions:start + required
        ]
        folds.append(ResearchFold(
            number=len(folds) + 1,
            train_dates=train_dates,
            embargo_dates=embargo_dates,
            test_dates=test_dates,
            train_bars=tuple(bar for day in train_dates for bar in sessions[day]),
            test_bars=tuple(bar for day in test_dates for bar in sessions[day]),
        ))
    return tuple(folds)


def _validate_fold_session_bars(bars, dates, role):
    """Recheck public fold tapes, including their claimed training sessions."""
    if type(bars) is not tuple or len(bars) != 390 * len(dates):
        raise ValueError(f"Research fold {role} bars do not match {role} dates")
    previous_stamp = None
    for index, bar in enumerate(bars):
        stamp = getattr(bar, "timestamp", None)
        if (
            not isinstance(stamp, datetime)
            or stamp.tzinfo is None or stamp.utcoffset() is None
            or stamp.second != 0 or stamp.microsecond != 0
            or (previous_stamp is not None and stamp <= previous_stamp)
        ):
            raise ValueError(f"Invalid or nonchronological research fold {role} timestamp")
        previous_stamp = stamp
        local = stamp.astimezone(_NEW_YORK)
        expected_date = dates[index // 390]
        expected_minute = 9 * 60 + 30 + index % 390
        if (
            local.date() != expected_date
            or local.hour * 60 + local.minute != expected_minute
        ):
            raise ValueError(f"Research fold {role} bars do not match {role} dates/minutes")
        prices = tuple(
            getattr(bar, key, None) for key in ("open", "high", "low", "close")
        )
        if any(
            type(price) not in (int, float)
            or not isfinite(price) or price <= 0
            for price in prices
        ):
            raise ValueError(f"Invalid research fold {role} price")
        opening, high, low, close = prices
        if high < max(opening, low, close) or low > min(opening, high, close):
            raise ValueError(f"Inconsistent research fold {role} OHLC bar")
        volume = getattr(bar, "volume", None)
        if type(volume) is not int or volume <= 0:
            raise ValueError(f"Invalid research fold {role} volume")


def evaluate_fixed_baseline_folds(
    folds, *, starting_cash=1000.0, risk_per_trade=0.015,
    slippage_pct=0.001,
):
    """Evaluate the unchanged opening-range baseline on test sessions only.

    Each fold starts with independent hypothetical capital. Fold PnL must
    NOT be added together as though one continuous portfolio were traded.
    This is not parameter tuning, AI evaluation, or a statistical edge claim.
    """
    if type(folds) not in (tuple, list) or not folds:
        raise ValueError("At least one research fold is required")
    if type(starting_cash) not in (int, float) or not isfinite(starting_cash) or starting_cash <= 0:
        raise ValueError("Invalid starting cash")
    results = []
    seen_test_dates = set()
    for fold in folds:
        if not isinstance(fold, ResearchFold) or not fold.test_dates:
            raise ValueError("Invalid research fold")
        if (
            set(fold.test_dates) & (
                set(fold.train_dates) | set(fold.embargo_dates) | seen_test_dates
            )
        ):
            raise ValueError("Overlapping research fold test dates")
        # Public folds can be constructed without using the strict splitter.
        # Verify chronological separation and the complete underlying test
        # tape before it can be presented as out-of-sample performance.
        for dates in (fold.train_dates, fold.embargo_dates, fold.test_dates):
            if (
                type(dates) is not tuple
                or any(type(day) is not date or day.weekday() >= 5 for day in dates)
                or tuple(sorted(set(dates))) != dates
            ):
                raise ValueError("Invalid research fold session dates")
        if (
            not fold.train_dates
            or fold.train_dates[-1] >= fold.test_dates[0]
            or (fold.embargo_dates and (
                fold.train_dates[-1] >= fold.embargo_dates[0]
                or fold.embargo_dates[-1] >= fold.test_dates[0]
            ))
        ):
            raise ValueError("Research fold dates are not chronological")
        # A public fold can be hand-built: independently validate BOTH
        # tapes, so a forged training window cannot be reported as a valid
        # chronological research fold even when the baseline uses only tests.
        _validate_fold_session_bars(fold.train_bars, fold.train_dates, "train")
        _validate_fold_session_bars(fold.test_bars, fold.test_dates, "test")
        seen_test_dates.update(fold.test_dates)
        signals = generate_breakout_signals(fold.test_bars)
        trades = simulate_trades(
            fold.test_bars, signals, starting_cash=starting_cash,
            risk_per_trade=risk_per_trade, slippage_pct=slippage_pct,
        )
        net_pnl = sum(
            (trade.exit_price - trade.entry_price) * trade.quantity
            for trade in trades
        )
        if not isfinite(net_pnl) or not isfinite(starting_cash + net_pnl):
            raise ValueError("Non-finite fixed-baseline fold result")
        results.append(FixedBaselineFoldResult(
            number=fold.number,
            first_test_date=fold.test_dates[0],
            last_test_date=fold.test_dates[-1],
            signal_count=len(signals),
            trade_count=len(trades),
            net_pnl=net_pnl,
            return_pct=100 * net_pnl / starting_cash,
            ending_cash=starting_cash + net_pnl,
        ))
    return tuple(results)
