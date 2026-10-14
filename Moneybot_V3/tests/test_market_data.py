
"""Tests for Moneybot V3's read-only market data connection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import market_data


def make_daily_bars(count=20, price=12.0, volume=2_000_000):
    """Create simulated daily stock prices."""

    return [
        {
            "t": f"2026-09-{day:02d}T04:00:00Z",
            "o": price,
            "h": price + 0.20,
            "l": price - 0.20,
            "c": price,
            "v": volume,
        }
        for day in range(1, count + 1)
    ]


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing Alpaca credentials"):
        market_data._credentials()


def test_latest_quote(monkeypatch):
    def fake_get_json(url):
        assert "quotes/latest" in url
        assert "feed=iex" in url
        return {"quote": {"bp": 11.99, "ap": 12.00}}

    monkeypatch.setattr(market_data, "_get_json", fake_get_json)

    bid, ask = market_data.get_latest_quote("TEST")

    assert bid == 11.99
    assert ask == 12.00


def test_missing_quote(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_get_json",
        lambda url: {"quote": {}},
    )

    with pytest.raises(RuntimeError, match="Missing bid-ask quote"):
        market_data.get_latest_quote("TEST")


def test_invalid_symbol():
    with pytest.raises(ValueError):
        market_data.get_latest_quote("../BAD")


def test_invalid_history_window():
    with pytest.raises(ValueError, match="days must be"):
        market_data.get_recent_daily_bars("TEST", days=0)


def test_daily_bars(monkeypatch):
    expected = make_daily_bars()

    def fake_get_json(url):
        assert "timeframe=1Day" in url
        assert "feed=iex" in url
        return {"bars": expected, "next_page_token": None}

    monkeypatch.setattr(market_data, "_get_json", fake_get_json)

    bars = market_data.get_recent_daily_bars("TEST")

    assert len(bars) == 20
    assert bars[0]["c"] == 12.0


def test_daily_bar_pagination(monkeypatch):
    calls = []

    def fake_get_json(url):
        calls.append(url)

        if "page_token=second" in url:
            return {
                "bars": make_daily_bars(2),
                "next_page_token": None,
            }

        return {
            "bars": make_daily_bars(1),
            "next_page_token": "second",
        }

    monkeypatch.setattr(market_data, "_get_json", fake_get_json)

    bars = market_data.get_recent_daily_bars("TEST")

    assert len(bars) == 3
    assert len(calls) == 2


def test_build_stock_candidate(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "get_recent_daily_bars",
        lambda symbol: make_daily_bars(),
    )

    monkeypatch.setattr(
        market_data,
        "get_latest_quote",
        lambda symbol: (11.99, 12.00),
    )

    candidate = market_data.get_stock_candidate(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert candidate.symbol == "TEST"
    assert candidate.price == 12.00
    assert candidate.average_daily_volume == 2_000_000
    assert candidate.market_cap == 1_000_000_000
    assert candidate.bid == 11.99
    assert candidate.ask == 12.00


def test_insufficient_daily_history(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "get_recent_daily_bars",
        lambda symbol: make_daily_bars(10),
    )

    with pytest.raises(RuntimeError, match="Not enough daily bars"):
        market_data.get_stock_candidate(
            "TEST",
            market_cap=1_000_000_000,
        )


def test_market_cap_required():
    with pytest.raises(ValueError, match="numeric market cap"):
        market_data.get_stock_candidate(
            "TEST",
            market_cap=None,
        )


def test_market_cap_cannot_be_boolean():
    with pytest.raises(ValueError, match="numeric market cap"):
        market_data.get_stock_candidate(
            "TEST",
            market_cap=True,
        )
