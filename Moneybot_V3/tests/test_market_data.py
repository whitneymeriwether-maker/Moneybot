
"""Tests for Moneybot V3 read-only market data.

All tests use simulated data. No orders or network calls.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import market_data


def make_daily_bars(count=20, price=12.0, volume=2_000_000):
    """Create simulated daily stock prices."""

    dates = []
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)

    return [
        {
            "t": f"{day.isoformat()}T04:00:00Z",
            "o": price,
            "h": price + 0.20,
            "l": price - 0.20,
            "c": price,
            "v": volume,
        }
        for day in reversed(dates)
    ]


def fresh_quote_timestamp():
    """Return a recent timestamp for mocked quotes."""

    return datetime.now(timezone.utc).isoformat()


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing Alpaca credentials"):
        market_data._credentials()


def test_latest_quote(monkeypatch):
    def fake_get_json(url):
        assert "quotes/latest" in url
        assert "feed=iex" in url

        return {
            "quote": {
                "bp": 11.99,
                "ap": 12.00,
                "t": fresh_quote_timestamp(),
            }
        }

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


def test_quote_missing_timestamp(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_get_json",
        lambda url: {
            "quote": {"bp": 11.99, "ap": 12.00}
        },
    )

    with pytest.raises(RuntimeError, match="Missing quote timestamp"):
        market_data.get_latest_quote("TEST")


def test_stale_quote(monkeypatch):
    old_timestamp = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()

    monkeypatch.setattr(
        market_data,
        "_get_json",
        lambda url: {
            "quote": {
                "bp": 11.99,
                "ap": 12.00,
                "t": old_timestamp,
            }
        },
    )

    with pytest.raises(RuntimeError, match="Stale quote"):
        market_data.get_latest_quote("TEST")


@pytest.mark.parametrize(
    "bid,ask",
    [
        (0, 12.00),
        (-1, 12.00),
        (12.00, 0),
        (12.01, 12.00),
        (12.00, 12.00),
        (float("nan"), 12.00),
        (11.99, float("inf")),
    ],
)
def test_invalid_bid_ask(monkeypatch, bid, ask):
    monkeypatch.setattr(
        market_data,
        "_get_json",
        lambda url: {
            "quote": {
                "bp": bid,
                "ap": ask,
                "t": fresh_quote_timestamp(),
            }
        },
    )

    with pytest.raises(RuntimeError, match="Invalid bid-ask quote"):
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

        return {
            "bars": expected,
            "next_page_token": None,
        }

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



def test_repeated_daily_bar_page_token_fails_closed(monkeypatch):
    calls = []

    def fake_get_json(url):
        calls.append(url)
        return {
            "bars": make_daily_bars(1),
            "next_page_token": "repeated",
        }

    monkeypatch.setattr(market_data, "_get_json", fake_get_json)

    with pytest.raises(RuntimeError, match="Invalid daily bars pagination"):
        market_data.get_recent_daily_bars("TEST")

    # The second response repeats the first page token; do not loop.
    assert len(calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"bars": None, "next_page_token": None},
        {"bars": "not a list", "next_page_token": None},
        {"bars": [], "next_page_token": 123},
        {"bars": [], "next_page_token": ""},
    ],
)
def test_malformed_daily_bar_page_fails_closed(monkeypatch, payload):
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)

    with pytest.raises(RuntimeError, match="Invalid daily bars"):
        market_data.get_recent_daily_bars("TEST")


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



@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"v": -1},
        {"v": float("nan")},
        {"v": True},
        {"c": float("inf")},
        {"c": 0},
        {"h": 11.0},
        {"l": 13.0},
        {"o": -1},
        {"t": "invalid"},
        {"t": "2026-09-20T04:00:00"},
        {"t": "2099-09-20T04:00:00Z"},
    ],
)
def test_malformed_daily_bar_fails_closed(monkeypatch, invalid_fields):
    bars = make_daily_bars()
    bars[-1].update(invalid_fields)

    monkeypatch.setattr(
        market_data,
        "get_recent_daily_bars",
        lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data,
        "get_latest_quote",
        lambda symbol: (11.99, 12.00),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_stock_candidate(
            "TEST", market_cap=1_000_000_000
        )


def test_duplicate_daily_bar_date_fails_closed(monkeypatch):
    bars = make_daily_bars()
    bars[-1]["t"] = bars[-2]["t"]

    monkeypatch.setattr(
        market_data,
        "get_recent_daily_bars",
        lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data,
        "get_latest_quote",
        lambda symbol: (11.99, 12.00),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_stock_candidate(
            "TEST", market_cap=1_000_000_000
        )



def test_stale_daily_history_fails_closed(monkeypatch):
    bars = make_daily_bars()
    for bar in bars:
        bar["t"] = (
            datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
            - timedelta(days=30)
        ).isoformat()

    monkeypatch.setattr(
        market_data,
        "get_recent_daily_bars",
        lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data,
        "get_latest_quote",
        lambda symbol: (11.99, 12.00),
    )

    with pytest.raises(RuntimeError, match="Stale daily bars"):
        market_data.get_stock_candidate(
            "TEST", market_cap=1_000_000_000
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
