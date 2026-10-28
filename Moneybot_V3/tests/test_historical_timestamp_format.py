"""Canonical historical minute-bar CSV timestamp regression tests (offline)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_data import load_price_bars


def _csv(tmp_path, stamp):
    path = tmp_path / "minute.csv"
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        f'"{stamp}",100,101,99,100,1000\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("stamp", [
    "20260105T093000-05:00",
    "2026-W02-1T09:30:00-05:00",
    "2026-01-05 09:30:00-05:00",
    "2026-01-05T09:30-05:00",
    "2026-01-05T09:30:00-05:00:00",
    "2026-01-05T09:30:00,000-05:00",
])
def test_noncanonical_csv_timestamp_rejected(tmp_path, stamp):
    with pytest.raises(ValueError, match="Noncanonical historical CSV timestamp"):
        load_price_bars(_csv(tmp_path, stamp))


@pytest.mark.parametrize("stamp", [
    "2026-01-05T09:30:00-05:00",
    "2026-01-05T14:30:00Z",
    "2026-01-05T20:00:00+05:30",
    "2026-01-05T14:30:00.000000000+00:00",
])
def test_canonical_utc_minute_aligned_csv_timestamp_accepted(tmp_path, stamp):
    bars = load_price_bars(_csv(tmp_path, stamp))
    assert len(bars) == 1
    assert bars[0].volume == 1000


def test_second_resolution_offset_still_fails_utc_alignment(tmp_path):
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        load_price_bars(_csv(tmp_path, "2026-01-05T09:30:00-05:00:30"))
