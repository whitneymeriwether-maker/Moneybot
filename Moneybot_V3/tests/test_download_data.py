
"""Tests for Moneybot V3's historical stock downloader."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

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
