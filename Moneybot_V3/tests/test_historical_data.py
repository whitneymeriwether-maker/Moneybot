
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_data import load_price_bars


def write_csv(tmp_path, rows):
    filename = tmp_path / "prices.csv"
    filename.write_text(
        "timestamp,open,high,low,close,volume\n" + rows,
        encoding="utf-8",
    )
    return filename


def test_valid_historical_prices(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103,10000\n"
        "2026-01-05T09:31:00-05:00,103,106,102,105,12000\n",
    )

    bars = load_price_bars(filename)

    assert len(bars) == 2
    assert bars[0].open == 100
    assert bars[1].close == 105
    assert bars[1].volume == 12000


def test_rejects_negative_price(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,-100,105,99,103,10000\n",
    )

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_inconsistent_high(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,98,99,103,10000\n",
    )

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_negative_volume(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103,-10\n",
    )

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_duplicate_timestamp(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103,10000\n"
        "2026-01-05T09:30:00-05:00,103,106,102,105,12000\n",
    )

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_missing_timezone(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00,100,105,99,103,10000\n",
    )

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_empty_data(tmp_path):
    filename = write_csv(tmp_path, "")

    with pytest.raises(ValueError):
        load_price_bars(filename)


def test_rejects_subminute_historical_timestamp(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:30-05:00,100,105,99,103,10000\n",
    )
    with pytest.raises(ValueError, match="minute-aligned"):
        load_price_bars(filename)


def test_rejects_unrepresentably_large_historical_volume(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103," + "9" * 400 + "\n",
    )
    with pytest.raises(ValueError, match="Invalid historical volume"):
        load_price_bars(filename)
