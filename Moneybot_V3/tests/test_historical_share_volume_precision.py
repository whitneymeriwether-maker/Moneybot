"""Exact whole-share volume bounds for offline V3 historical research.

Synthetic observations only; no network access, orders, or brokerage activity.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_data import PriceBar, load_price_bars
from backtesting.walk_forward import (
    ResearchFold,
    build_research_folds,
    evaluate_fixed_baseline_folds,
)


MAX_SAFE = (1 << 53) - 1
EASTERN = ZoneInfo("America/New_York")


def _csv(tmp_path, volume):
    filename = tmp_path / "history.csv"
    filename.write_text(
        "timestamp,open,high,low,close,volume\n"
        f"2026-10-12T09:30:00-04:00,10,11,9,10,{volume}\n",
        encoding="utf-8",
    )
    return filename


def _bar(day, minute, volume=1000):
    return PriceBar(
        timestamp=datetime(day.year, day.month, day.day, 9, 30, tzinfo=EASTERN)
        + timedelta(minutes=minute),
        open=10.0, high=11.0, low=9.0, close=10.0,
        volume=volume,
    )


def test_historical_reader_accepts_largest_exact_whole_share_volume(tmp_path):
    bars = load_price_bars(_csv(tmp_path, MAX_SAFE))
    assert bars[0].volume == MAX_SAFE


@pytest.mark.parametrize("volume", [MAX_SAFE + 1, MAX_SAFE + 2, 10 ** 100])
def test_historical_reader_rejects_inexact_whole_share_volume(tmp_path, volume):
    with pytest.raises(ValueError, match="Invalid historical volume"):
        load_price_bars(_csv(tmp_path, volume))


def test_direct_fold_builder_rejects_inexact_whole_share_volume():
    with pytest.raises(ValueError, match="traded minute volumes"):
        build_research_folds(
            [_bar(date(2026, 10, 12), 0, MAX_SAFE + 1)],
            train_sessions=1, test_sessions=1,
        )


@pytest.mark.parametrize("corrupted_role", ["train", "test"])
def test_direct_fold_evaluator_rejects_inexact_volume_in_either_tape(corrupted_role):
    train_day = date(2026, 10, 12)
    test_day = date(2026, 10, 13)
    train = [_bar(train_day, minute) for minute in range(390)]
    test = [_bar(test_day, minute) for minute in range(390)]
    tape = train if corrupted_role == "train" else test
    tape[100] = _bar(train_day if corrupted_role == "train" else test_day, 100, MAX_SAFE + 1)
    fold = ResearchFold(
        number=1,
        train_dates=(train_day,),
        embargo_dates=(),
        test_dates=(test_day,),
        train_bars=tuple(train),
        test_bars=tuple(test),
    )
    with pytest.raises(ValueError, match="volume"):
        evaluate_fixed_baseline_folds((fold,))
