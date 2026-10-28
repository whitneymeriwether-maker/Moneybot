
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


def test_rejects_duplicate_header_that_overrides_volume(tmp_path):
    filename = tmp_path / "duplicate.csv"
    filename.write_text(
        "timestamp,open,high,low,close,volume,volume\n"
        "2026-01-05T09:30:00-05:00,100,105,99,103,0,10000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate historical CSV columns"):
        load_price_bars(filename)


def test_rejects_extra_cell_that_dictreader_would_ignore(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103,10000,unverified\n",
    )
    with pytest.raises(ValueError, match="Malformed historical CSV row"):
        load_price_bars(filename)


def test_rejects_missing_cell_that_dictreader_fills_with_none(tmp_path):
    filename = write_csv(
        tmp_path,
        "2026-01-05T09:30:00-05:00,100,105,99,103\n",
    )
    with pytest.raises(ValueError, match="Malformed historical CSV row"):
        load_price_bars(filename)


def test_rejects_unnamed_header_column(tmp_path):
    filename = tmp_path / "unnamed.csv"
    filename.write_text(
        "timestamp,open,high,low,close,volume,\n"
        "2026-01-05T09:30:00-05:00,100,105,99,103,10000,ignored\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unnamed historical CSV column"):
        load_price_bars(filename)


def test_allows_named_extra_metadata_column_with_complete_rows(tmp_path):
    filename = tmp_path / "metadata.csv"
    filename.write_text(
        "timestamp,open,high,low,close,volume,source\n"
        "2026-01-05T09:30:00-05:00,100,105,99,103,10000,iex\n",
        encoding="utf-8",
    )
    bars = load_price_bars(filename)
    assert len(bars) == 1
    assert bars[0].volume == 10000


def test_rejects_local_minute_aligned_but_utc_half_minute(tmp_path):
    # An explicit offset with seconds can make 09:30:00 a 13:29:30 UTC
    # instant. It must not be treated as a real one-minute observation.
    filename = write_csv(
        tmp_path,
        "2026-04-01T09:30:00-04:00:30,100,105,99,103,10000\n",
    )
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        load_price_bars(filename)
