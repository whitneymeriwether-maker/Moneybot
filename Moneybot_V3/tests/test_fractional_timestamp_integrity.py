"""Fail-closed tests for provider timestamp normalization (offline only)."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting import download_data
from backtesting.historical_data import load_price_bars


def _mock_provider(monkeypatch, tmp_path, timestamp):
    monkeypatch.setenv("APCA_API_KEY_ID", "offline-test-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "offline-test-secret")
    monkeypatch.setattr(
        download_data, "__file__",
        str(tmp_path / "Moneybot_V3" / "backtesting" / "download_data.py"),
    )
    payload = {"bars": {"SPY": [{
        "t": timestamp, "o": 100, "h": 101,
        "l": 99, "c": 100, "v": 1000,
    }]}, "next_page_token": None}
    monkeypatch.setattr(
        download_data, "urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(payload).encode()),
    )


@pytest.mark.parametrize("timestamp", [
    "20260401T133000Z",             # Compact ISO date/time.
    "2026-W14-3T13:30:00Z",         # ISO week date.
    "2026-04-01 13:30:00Z",         # Space separator.
    "2026-04-01T13:30Z",            # Missing seconds.
    "2026-04-01T13:30:00.0000000000Z",  # Too many fractional digits.
])
def test_download_rejects_noncanonical_provider_text_without_overwrite(
    monkeypatch, tmp_path, timestamp,
):
    _mock_provider(monkeypatch, tmp_path, timestamp)
    directory = tmp_path / "Moneybot_V3" / "data"
    directory.mkdir(parents=True)
    output = directory / "SPY_1min_2026_04_to_09.csv"
    output.write_text("previous verified research data", encoding="utf-8")

    with pytest.raises(ValueError, match="(Noncanonical|Invalid historical bar timestamp)"):
        download_data.download_history("SPY")

    assert output.read_text(encoding="utf-8") == "previous verified research data"
    assert [path.name for path in directory.iterdir()] == [output.name]


@pytest.mark.parametrize("timestamp", [
    "2026-04-01T13:30:00.000000001Z",
    "2026-04-01T13:30:00.000000010Z",
    "2026-04-01T09:30:00.000000001-04:00",
])
def test_download_rejects_submicrosecond_nonzero_timestamp(
    monkeypatch, tmp_path, timestamp,
):
    _mock_provider(monkeypatch, tmp_path, timestamp)
    directory = tmp_path / "Moneybot_V3" / "data"
    directory.mkdir(parents=True)
    output = directory / "SPY_1min_2026_04_to_09.csv"
    output.write_text("previous validated data", encoding="utf-8")

    with pytest.raises(ValueError, match="minute-aligned"):
        download_data.download_history("SPY")

    assert output.read_text(encoding="utf-8") == "previous validated data"
    assert [path.name for path in directory.iterdir()] == [output.name]


@pytest.mark.parametrize("timestamp", [
    "2026-04-01T13:30:00.000000000Z",
    "2026-04-01T09:30:00.000000000-04:00",
])
def test_download_accepts_exact_zero_nanosecond_fraction(
    monkeypatch, tmp_path, timestamp,
):
    _mock_provider(monkeypatch, tmp_path, timestamp)
    output = download_data.download_history("SPY")
    assert output.read_text(encoding="utf-8").splitlines()[1].startswith(
        "2026-04-01T13:30:00+00:00,"
    )


@pytest.mark.parametrize("timestamp", [
    "2026-04-01T13:30:00.000000001Z",
    "2026-04-01T09:30:00.000000010-04:00",
])
def test_csv_reader_rejects_submicrosecond_nonzero_timestamp(tmp_path, timestamp):
    csv = tmp_path / "minute.csv"
    csv.write_text(
        "timestamp,open,high,low,close,volume\n"
        f"{timestamp},100,101,99,100,1000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        load_price_bars(csv)


def test_csv_reader_accepts_zero_nanosecond_fraction(tmp_path):
    csv = tmp_path / "minute.csv"
    csv.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-04-01T13:30:00.000000000Z,100,101,99,100,1000\n",
        encoding="utf-8",
    )
    assert len(load_price_bars(csv)) == 1
