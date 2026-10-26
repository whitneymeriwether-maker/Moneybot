"""Regression tests for explicit NYSE research-session completeness."""

import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.pipeline import run_backtest, validate_research_window
from backtesting.run_backtest import NYSE_2026_APR_SEP_CLOSED_SESSIONS

NY = ZoneInfo("America/New_York")
APRIL_HOLIDAY = date(2026, 4, 3)
FIRST = date(2026, 4, 1)
LAST = date(2026, 4, 8)


def _bars(days, utc=False):
    return [
        SimpleNamespace(timestamp=(
            datetime(day.year, day.month, day.day, 13, 30, tzinfo=timezone.utc)
            if utc else datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
        ))
        for day in days
    ]


def test_calendar_rejects_missing_interior_session_even_above_count_floor():
    days = [date(2026, 4, d) for d in (1, 2, 6, 8)]
    # Previous endpoint/count checks accepted this file despite missing Apr 7.
    validate_research_window(_bars(days), FIRST, LAST, 4)
    with pytest.raises(ValueError, match="missing 1 session"):
        validate_research_window(
            _bars(days), FIRST, LAST, 4, closed_sessions={APRIL_HOLIDAY},
        )


def test_calendar_accepts_full_trading_span_excluding_official_holiday():
    days = [date(2026, 4, d) for d in (1, 2, 6, 7, 8)]
    validate_research_window(
        _bars(days, utc=True), FIRST, LAST, 5,
        closed_sessions={APRIL_HOLIDAY},
    )


def test_calendar_rejects_unexpected_holiday_session():
    days = [date(2026, 4, d) for d in (1, 2, 3, 6, 7, 8)]
    with pytest.raises(ValueError, match="unexpected 1 session"):
        validate_research_window(
            _bars(days), FIRST, LAST, 5, closed_sessions={APRIL_HOLIDAY},
        )


@pytest.mark.parametrize("invalid", [
    True,
    "2026-04-03",
    ["2026-04-03"],
    [APRIL_HOLIDAY, APRIL_HOLIDAY],
    {date(2026, 4, 4)},  # Weekend is not an exchange holiday override.
    {date(2026, 3, 31)},  # Outside requested window.
    {datetime(2026, 4, 3)},  # A datetime is not a date-only closure.
])
def test_calendar_rejects_malformed_or_ambiguous_closures(invalid):
    with pytest.raises(ValueError, match="Invalid exchange closure calendar"):
        validate_research_window(
            _bars([FIRST, LAST]), FIRST, LAST,
            closed_sessions=invalid,
        )


def test_calendar_requires_explicit_research_window():
    with pytest.raises(ValueError, match="requires a session span"):
        run_backtest("not-needed.csv", closed_sessions=frozenset())


def test_pipeline_enforces_calendar_before_simulation(tmp_path):
    filename = tmp_path / "missing_session.csv"
    days = [date(2026, 4, d) for d in (1, 2, 6, 8)]
    with filename.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
        for bar in _bars(days):
            writer.writerow((bar.timestamp.isoformat(), 100, 101, 99, 100, 100))

    baseline = run_backtest(
        filename, expected_session_span=(FIRST, LAST),
        minimum_observed_sessions=4,
    )
    assert baseline.trade_count == 0
    with pytest.raises(ValueError, match="missing 1 session"):
        run_backtest(
            filename, expected_session_span=(FIRST, LAST),
            minimum_observed_sessions=4,
            closed_sessions={APRIL_HOLIDAY},
        )


def test_runner_uses_verified_five_holidays_and_126_expected_sessions():
    assert NYSE_2026_APR_SEP_CLOSED_SESSIONS == frozenset({
        date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
        date(2026, 7, 3), date(2026, 9, 7),
    })
    first, last = date(2026, 4, 1), date(2026, 9, 30)
    days = [
        first + timedelta(days=i)
        for i in range((last - first).days + 1)
    ]
    trading_days = [
        day for day in days
        if day.weekday() < 5 and day not in NYSE_2026_APR_SEP_CLOSED_SESSIONS
    ]
    assert len(trading_days) == 126
    validate_research_window(
        _bars(trading_days), first, last,
        minimum_observed_sessions=120,
        closed_sessions=NYSE_2026_APR_SEP_CLOSED_SESSIONS,
    )
