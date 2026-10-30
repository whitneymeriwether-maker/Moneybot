"""Fail-closed validation for zero-volume synthetic regular-session bars."""

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.pipeline import run_backtest, validate_traded_regular_minutes
import backtesting.run_backtest as runner

NY = ZoneInfo("America/New_York")


def _bar(year, month, day, hour, minute, volume, tz=NY):
    return SimpleNamespace(
        timestamp=datetime(year, month, day, hour, minute, tzinfo=tz),
        volume=volume,
    )


def test_strict_check_rejects_zero_volume_at_open():
    with pytest.raises(ValueError, match="Zero-volume regular-session minute"):
        validate_traded_regular_minutes([_bar(2026, 10, 12, 9, 30, 0)])


def test_strict_check_rejects_zero_volume_with_utc_offset():
    # 13:45 UTC is 09:45 New York on October 12.
    with pytest.raises(ValueError, match="Zero-volume regular-session minute"):
        validate_traded_regular_minutes([
            _bar(2026, 10, 12, 13, 45, 0, tz=timezone.utc)
        ])


def test_strict_check_ignores_extended_hours_and_weekend():
    validate_traded_regular_minutes([
        _bar(2026, 10, 12, 9, 29, 0),
        _bar(2026, 10, 12, 9, 30, 100),
        _bar(2026, 10, 12, 15, 59, 100),
        _bar(2026, 10, 12, 16, 0, 0),
        _bar(2026, 10, 17, 10, 0, 0),
    ])


def test_strict_check_accepts_positive_regular_volume():
    validate_traded_regular_minutes([
        _bar(2026, 10, 12, 9, 30, 1),
        _bar(2026, 10, 12, 9, 31, 100),
    ])


def test_pipeline_rejects_zero_volume_even_with_complete_timestamps(tmp_path):
    filename = tmp_path / "prices.csv"
    start = datetime(2026, 10, 12, 9, 30, tzinfo=NY)
    with filename.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "open", "high", "low", "close", "volume"))
        for minute in range(390):
            writer.writerow((
                (start + timedelta(minutes=minute)).isoformat(),
                100, 100, 100, 100, 0 if minute == 15 else 1000,
            ))

    # The timestamp completeness checks alone do not detect this.
    baseline = run_backtest(filename, require_full_regular_sessions=True)
    assert baseline.trade_count == 0

    with pytest.raises(ValueError, match="Zero-volume regular-session minute"):
        run_backtest(
            filename, require_full_regular_sessions=True,
            require_traded_regular_minutes=True,
        )


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", [], float("nan")])
def test_pipeline_rejects_non_boolean_strict_option(invalid):
    with pytest.raises(ValueError, match="Invalid traded regular-minute requirement"):
        run_backtest("unused.csv", require_traded_regular_minutes=invalid)


def test_six_month_runner_enables_strict_traded_minutes(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "SPY_1min_2026_04_to_09.csv").write_text(
        "placeholder", encoding="utf-8"
    )
    monkeypatch.setattr(runner, "V3_FOLDER", tmp_path)
    seen = {}

    class Checked(Exception):
        pass

    def check_call(**kwargs):
        seen.update(kwargs)
        raise Checked()

    monkeypatch.setattr(runner, "run_backtest", check_call)
    with pytest.raises(Checked):
        runner.main()
    assert seen["require_full_regular_sessions"] is True
    assert seen["require_traded_regular_minutes"] is True


@pytest.mark.parametrize("invalid_volume", [
    -1, 1.5, 1.0, True, "100", None,
    float("nan"), float("inf"), (1 << 53),
])
def test_direct_traded_minute_check_rejects_invalid_share_counts(invalid_volume):
    # Direct callers must not certify malformed in-memory volumes as traded.
    with pytest.raises(ValueError, match="Invalid regular-session share volume"):
        validate_traded_regular_minutes([
            _bar(2026, 10, 12, 9, 30, invalid_volume)
        ])


@pytest.mark.parametrize("valid_volume", [1, (1 << 53) - 1])
def test_direct_traded_minute_check_accepts_exact_positive_share_bounds(valid_volume):
    validate_traded_regular_minutes([
        _bar(2026, 10, 12, 9, 30, valid_volume)
    ])
