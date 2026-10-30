"""Strict full-session backtests must not inherit relaxed exploratory gap settings.

All data are synthetic and local; no providers, brokers, or orders.
"""
import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backtesting.pipeline import run_backtest


def _write_session(tmp_path, *, missing_minute=None):
    path = tmp_path / "synthetic_session.csv"
    start = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=("timestamp", "open", "high", "low", "close", "volume")
        )
        writer.writeheader()
        for minute in range(390):
            if minute == missing_minute:
                continue
            writer.writerow({
                "timestamp": (start + timedelta(minutes=minute)).isoformat(),
                "open": 100, "high": 101, "low": 99, "close": 100,
                "volume": 1000,
            })
    return path


@pytest.mark.parametrize("relaxed_gap", [2, 390])
def test_strict_full_session_rejects_missing_interior_minute_even_with_relaxed_gap(
    tmp_path, relaxed_gap
):
    tape = _write_session(tmp_path, missing_minute=120)
    with pytest.raises(ValueError, match="Missing regular-session minute bars"):
        run_backtest(
            tape, require_full_regular_sessions=True,
            max_regular_gap_minutes=relaxed_gap,
        )


def test_exploratory_gap_tolerance_still_permits_sparse_session(tmp_path):
    tape = _write_session(tmp_path, missing_minute=120)
    report = run_backtest(tape, max_regular_gap_minutes=2)
    assert report.trade_count == 0


def test_complete_session_remains_valid_with_relaxed_gap_option(tmp_path):
    tape = _write_session(tmp_path)
    report = run_backtest(
        tape, require_full_regular_sessions=True, max_regular_gap_minutes=2
    )
    assert report.trade_count == 0
