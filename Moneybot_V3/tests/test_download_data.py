
"""Tests for Moneybot V3's historical stock downloader."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import download_data
from backtesting.download_data import (
    DEFAULT_SYMBOL,
    RESEARCH_MIN_PRICE,
    RESEARCH_MAX_PRICE,
    download_history,
    validate_symbol,
)


def test_spy_remains_default():
    assert DEFAULT_SYMBOL == "SPY"


def test_research_price_range():
    assert RESEARCH_MIN_PRICE == 2.00
    assert RESEARCH_MAX_PRICE == 30.00


@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("SPY", "SPY"),
        ("spy", "SPY"),
        ("f", "F"),
        ("SOFI", "SOFI"),
        ("PLTR", "PLTR"),
        ("BRK.B", "BRK.B"),
        (" BRK.B ", "BRK.B"),
    ],
)
def test_valid_stock_symbols(symbol, expected):
    assert validate_symbol(symbol) == expected


@pytest.mark.parametrize(
    "symbol",
    [
        "",
        " ",
        "A B",
        "../SPY",
        "SPY/TEST",
        "SPY;TEST",
        "SPY_TEST",
        "ABCDEFGHIJK",
    ],
)
def test_invalid_stock_symbols(symbol):
    with pytest.raises(ValueError):
        validate_symbol(symbol)


def test_missing_alpaca_credentials(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="Missing Alpaca market-data credentials",
    ):
        download_history("SOFI")


def test_missing_alpaca_secret(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test-key")
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    with pytest.raises(
        RuntimeError,
        match="Missing Alpaca market-data credentials",
    ):
        download_history("SOFI")


def test_missing_alpaca_key(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")

    with pytest.raises(
        RuntimeError,
        match="Missing Alpaca market-data credentials",
    ):
        download_history("SOFI")


def mock_download(monkeypatch, tmp_path, pages):
    """Stub HTTPS responses and redirect output to tmp_path."""
    monkeypatch.setenv("APCA_API_KEY_ID", "fake-test-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fake-test-secret")
    monkeypatch.setattr(
        download_data,
        "__file__",
        str(tmp_path / "Moneybot_V3" / "backtesting" / "download_data.py"),
    )
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert len(calls) <= len(pages), "Unexpected extra page request"
        return io.BytesIO(json.dumps(pages[len(calls) - 1]).encode())

    monkeypatch.setattr(download_data, "urlopen", fake_urlopen)
    return calls


def sample_bar(timestamp):
    return {
        "t": timestamp, "o": 100.0, "h": 101.0,
        "l": 99.0, "c": 100.0, "v": 1000,
    }


def test_download_follows_valid_pagination(monkeypatch, tmp_path):
    pages = [
        {
            "bars": {"SPY": [sample_bar("2026-04-01T13:30:00Z")]},
            "next_page_token": "next",
        },
        {
            "bars": {"SPY": [sample_bar("2026-04-01T13:31:00Z")]},
            "next_page_token": None,
        },
    ]
    calls = mock_download(monkeypatch, tmp_path, pages)

    output = download_history("SPY")

    assert output.is_file()
    assert len(output.read_text().splitlines()) == 3
    assert len(calls) == 2
    assert "page_token=next" in calls[1]


def test_download_rejects_repeated_page_token(monkeypatch, tmp_path):
    pages = [
        {"bars": {"SPY": []}, "next_page_token": "loop"},
        {"bars": {"SPY": []}, "next_page_token": "loop"},
    ]
    calls = mock_download(monkeypatch, tmp_path, pages)

    with pytest.raises(RuntimeError, match="Invalid historical pagination"):
        download_history("SPY")

    assert len(calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"bars": None, "next_page_token": None},
        {"bars": {"SPY": "not a list"}, "next_page_token": None},
        {"bars": {}, "next_page_token": ""},
        {"bars": {}, "next_page_token": 123},
    ],
)
def test_download_rejects_malformed_pages(monkeypatch, tmp_path, payload):
    mock_download(monkeypatch, tmp_path, [payload])

    with pytest.raises(RuntimeError, match="Invalid historical"):
        download_history("SPY")


def test_invalid_download_does_not_overwrite_good_csv(monkeypatch, tmp_path):
    output_dir = tmp_path / "Moneybot_V3" / "data"
    output_dir.mkdir(parents=True)
    output = output_dir / "SPY_1min_2026_04_to_09.csv"
    output.write_text("existing verified history", encoding="utf-8")
    duplicate = sample_bar("2026-04-01T13:30:00Z")
    mock_download(
        monkeypatch,
        tmp_path,
        [{"bars": {"SPY": [duplicate, duplicate]}, "next_page_token": None}],
    )

    with pytest.raises(ValueError, match="Timestamps must be increasing"):
        download_history("SPY")

    assert output.read_text(encoding="utf-8") == "existing verified history"
    assert sorted(path.name for path in output_dir.iterdir()) == [output.name]

def test_download_rejects_naive_timestamp_without_overwriting_csv(monkeypatch, tmp_path):
    # A timezone-free API timestamp must not silently inherit runner local time.
    output_dir = tmp_path / "Moneybot_V3" / "data"
    output_dir.mkdir(parents=True)
    output = output_dir / "SPY_1min_2026_04_to_09.csv"
    output.write_text("existing verified history", encoding="utf-8")
    mock_download(
        monkeypatch, tmp_path,
        [{"bars": {"SPY": [sample_bar("2026-04-01T13:30:00")]},
          "next_page_token": None}],
    )

    with pytest.raises(ValueError, match="timestamp must include timezone"):
        download_history("SPY")

    assert output.read_text(encoding="utf-8") == "existing verified history"
    assert sorted(path.name for path in output_dir.iterdir()) == [output.name]


def test_download_normalizes_explicit_offset_to_utc(monkeypatch, tmp_path):
    mock_download(
        monkeypatch, tmp_path,
        [{"bars": {"SPY": [sample_bar("2026-04-01T09:30:00-04:00")]},
          "next_page_token": None}],
    )

    output = download_history("SPY")
    assert output.read_text(encoding="utf-8").splitlines()[1].startswith(
        "2026-04-01T13:30:00+00:00,"
    )
