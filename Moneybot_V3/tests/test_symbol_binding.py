"""Historical research ticker identity must be bound to each CSV bar."""

import csv
import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting import download_data
from backtesting.historical_data import load_price_bars
from backtesting.pipeline import run_backtest
import backtesting.run_backtest as spy_runner


def write_bars(tmp_path, symbols):
    path = tmp_path / "history.csv"
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    if symbols is not None:
        columns.append("symbol")
    start = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for minute in range(2):
            row = {
                "timestamp": (start + timedelta(minutes=minute)).isoformat(),
                "open": 100, "high": 101, "low": 99, "close": 100,
                "volume": 1000,
            }
            if symbols is not None:
                row["symbol"] = symbols[minute]
            writer.writerow(row)
    return path


def test_loader_accepts_matching_symbol_on_every_bar(tmp_path):
    path = write_bars(tmp_path, ["SPY", "SPY"])
    assert len(load_price_bars(path, expected_symbol="SPY")) == 2
    assert run_backtest(path, expected_symbol="SPY").trade_count == 0


def test_loader_allows_legacy_unlabelled_only_without_expectation(tmp_path):
    path = write_bars(tmp_path, None)
    assert len(load_price_bars(path)) == 2
    with pytest.raises(ValueError, match="missing symbol metadata"):
        load_price_bars(path, expected_symbol="SPY")
    with pytest.raises(ValueError, match="missing symbol metadata"):
        run_backtest(path, expected_symbol="SPY")


def test_loader_rejects_renamed_other_ticker_history(tmp_path):
    path = write_bars(tmp_path, ["QQQ", "QQQ"])
    with pytest.raises(ValueError, match="does not match expected symbol"):
        run_backtest(path, expected_symbol="SPY")


def test_loader_rejects_mixed_symbols_even_without_expectation(tmp_path):
    path = write_bars(tmp_path, ["SPY", "QQQ"])
    with pytest.raises(ValueError, match="Mixed symbols"):
        load_price_bars(path)


@pytest.mark.parametrize("invalid", ["", "spy", " SPY", "SPY ", "../SPY", "A/B"])
def test_loader_rejects_invalid_symbol_metadata(tmp_path, invalid):
    path = write_bars(tmp_path, ["SPY", invalid])
    with pytest.raises(ValueError, match="Invalid historical symbol metadata"):
        load_price_bars(path)


@pytest.mark.parametrize("invalid", ["spy", "", True, 12, "../SPY"])
def test_loader_rejects_invalid_expected_symbol(tmp_path, invalid):
    path = write_bars(tmp_path, ["SPY", "SPY"])
    with pytest.raises(ValueError, match="Invalid expected historical symbol"):
        load_price_bars(path, expected_symbol=invalid)


def test_downloader_writes_verified_symbol_per_bar(monkeypatch, tmp_path):
    monkeypatch.setenv("APCA_API_KEY_ID", "fake")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake")
    monkeypatch.setattr(
        download_data, "__file__",
        str(tmp_path / "Moneybot_V3" / "backtesting" / "download_data.py"),
    )
    payload = {"bars": {"SPY": [{
        "t": "2026-04-01T13:30:00Z", "o": 100, "h": 101,
        "l": 99, "c": 100, "v": 1000,
    }]}, "next_page_token": None}
    monkeypatch.setattr(
        download_data, "urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(payload).encode()),
    )
    path = download_data.download_history("SPY")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert len(load_price_bars(path, expected_symbol="SPY")) == 1


def test_spy_runner_requires_symbol_metadata(tmp_path, monkeypatch):
    folder = tmp_path / "Moneybot_V3"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "SPY_1min_2026_04_to_09.csv").write_text("placeholder")
    monkeypatch.setattr(spy_runner, "V3_FOLDER", folder)
    received = {}

    class StopHere(Exception):
        pass

    def capture(**kwargs):
        received.update(kwargs)
        raise StopHere()

    monkeypatch.setattr(spy_runner, "run_backtest", capture)
    with pytest.raises(StopHere):
        spy_runner.main()
    assert received["expected_symbol"] == "SPY"
