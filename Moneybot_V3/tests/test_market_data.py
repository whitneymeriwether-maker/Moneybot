
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


@pytest.mark.parametrize("invalid", [True, False, 1.0, "45", None])
def test_history_window_rejects_non_integer_days(invalid):
    with pytest.raises(ValueError, match="days must be"):
        market_data.get_recent_daily_bars("TEST", days=invalid)


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
        {"v": 0},  # No observed trade supports a daily closing price.
        {"v": float("nan")},
        {"v": True},
        {"v": 1.5},  # API share volume cannot be fractional.
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


def test_weekend_daily_bar_is_not_verified_as_stock_history():
    bars = make_daily_bars()
    latest_date = datetime.fromisoformat(
        bars[-1]["t"].replace("Z", "+00:00")
    ).date()
    next_saturday = latest_date + timedelta(
        days=(5 - latest_date.weekday()) % 7
    )
    bars[-1]["t"] = f"{next_saturday.isoformat()}T04:00:00Z"

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data._validate_daily_bars(bars, "TEST")


def test_older_zero_volume_daily_bar_cannot_hide_outside_recent_window():
    bars = make_daily_bars(21)
    bars[0]["v"] = 0

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data._validate_daily_bars(bars, "TEST")


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
            # Preserve weekdays so this test isolates the stale-data gate.
            - timedelta(days=28)
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


@pytest.mark.parametrize(
    "payload",
    [None, [], "invalid", {"quote": [1]}, {"quote": "invalid"}],
)
def test_malformed_quote_response_fails_closed(monkeypatch, payload):
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)

    with pytest.raises(RuntimeError, match="Invalid quote response"):
        market_data.get_latest_quote("TEST")


def test_overflowed_daily_volume_average_is_unverified(monkeypatch):
    # Every daily volume is finite, but the 20-day sum overflows.
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars",
        lambda symbol: make_daily_bars(volume=1e308),
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote",
        lambda symbol: pytest.fail("Do not request a quote after bad volume"),
    )

    with pytest.raises(RuntimeError, match="Invalid daily volume average"):
        market_data.get_stock_candidate("TEST", market_cap=1_000_000_000)


@pytest.mark.parametrize("invalid_cap", [0, -1, float("nan"), float("inf"), 10 ** 400])
def test_stock_candidate_rejects_nonfinite_or_nonpositive_market_cap(invalid_cap):
    with pytest.raises(ValueError, match="finite positive market cap"):
        market_data.get_stock_candidate("TEST", market_cap=invalid_cap)


def test_daily_bars_sorted_by_utc_instant_not_offset_text(monkeypatch):
    # "10:00-04:00" is later than "13:59Z", despite text ordering.
    bars = make_daily_bars(2)
    day = make_daily_bars(1)[0]["t"][:10]
    bars[0]["t"] = f"{day}T10:00:00-04:00"
    bars[1]["t"] = f"{day}T13:59:00Z"
    monkeypatch.setattr(
        market_data, "_get_json",
        lambda url: {"bars": bars, "next_page_token": None},
    )

    result = market_data.get_recent_daily_bars("TEST")

    assert result[0]["t"] == f"{day}T13:59:00Z"
    assert result[1]["t"] == f"{day}T10:00:00-04:00"


@pytest.mark.parametrize("invalid_timestamp", [None, "not-a-date", "2026-04-01T13:59:00"])
def test_daily_bars_reject_invalid_timestamp_before_sorting(
    monkeypatch, invalid_timestamp,
):
    bars = make_daily_bars(1)
    bars[0]["t"] = invalid_timestamp
    monkeypatch.setattr(
        market_data, "_get_json",
        lambda url: {"bars": bars, "next_page_token": None},
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_recent_daily_bars("TEST")


def test_candidate_rejects_malformed_older_bar_outside_recent_twenty(monkeypatch):
    bars = make_daily_bars(21)
    bars[0]["v"] = -1  # Not part of bars[-20:].
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote",
        lambda symbol: pytest.fail("Do not quote after invalid history"),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_stock_candidate("TEST", market_cap=1_000_000_000)


def test_candidate_rejects_older_duplicate_date_outside_recent_twenty(monkeypatch):
    bars = make_daily_bars(21)
    bars[0]["t"] = bars[1]["t"]  # Hidden by previous bars[-20:] validation.
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote",
        lambda symbol: pytest.fail("Do not quote after duplicate history"),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_stock_candidate("TEST", market_cap=1_000_000_000)



def test_candidate_rejects_discontinuous_recent_daily_sample(monkeypatch):
    # The most recent bar is fresh, but a two-week gap separates the
    # twenty-bar sample. Its average volume is not a recent 20-session measure.
    bars = make_daily_bars()
    for bar in bars[:10]:
        stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        bar["t"] = (stamp - timedelta(days=14)).isoformat()
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote",
        lambda symbol: pytest.fail("Do not quote after a historical data gap"),
    )
    with pytest.raises(RuntimeError, match="Discontinuous recent daily bars"):
        market_data.get_stock_candidate("TEST", market_cap=1_000_000_000)


def test_candidate_accepts_normal_weekend_gaps(monkeypatch):
    bars = make_daily_bars()
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote", lambda symbol: (11.99, 12.00),
    )
    assert market_data.get_stock_candidate(
        "TEST", market_cap=1_000_000_000
    ).average_daily_volume == 2_000_000


@pytest.mark.parametrize("location", ["response", "quote"])
@pytest.mark.parametrize("field", ["symbol", "S"])
def test_quote_rejects_mismatched_provider_symbol(
    monkeypatch, location, field,
):
    payload = {
        "quote": {
            "bp": 11.99, "ap": 12.00, "t": fresh_quote_timestamp(),
        },
    }
    record = payload if location == "response" else payload["quote"]
    record[field] = "OTHER"
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)

    with pytest.raises(RuntimeError, match="Unexpected quote"):
        market_data.get_latest_quote("TEST")


def test_quote_accepts_matching_provider_symbol(monkeypatch):
    payload = {
        "symbol": "TEST",
        "quote": {
            "S": "TEST", "symbol": "TEST",
            "bp": 11.99, "ap": 12.00, "t": fresh_quote_timestamp(),
        },
    }
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)
    assert market_data.get_latest_quote("TEST") == (11.99, 12.00)


@pytest.mark.parametrize("field", ["bp", "ap"])
def test_quote_rejects_boolean_prices(monkeypatch, field):
    quote = {
        "bp": 11.99, "ap": 12.00, "t": fresh_quote_timestamp(),
    }
    quote[field] = True
    monkeypatch.setattr(
        market_data, "_get_json", lambda url: {"quote": quote},
    )
    with pytest.raises(RuntimeError, match="Invalid bid-ask quote"):
        market_data.get_latest_quote("TEST")


@pytest.mark.parametrize("location", ["response", "bar"])
@pytest.mark.parametrize("field", ["symbol", "S"])
def test_daily_bars_reject_mismatched_provider_symbol(
    monkeypatch, location, field,
):
    payload = {"bars": make_daily_bars(1), "next_page_token": None}
    record = payload if location == "response" else payload["bars"][0]
    record[field] = "OTHER"
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)
    with pytest.raises(RuntimeError, match="Unexpected daily bar"):
        market_data.get_recent_daily_bars("TEST")


def test_daily_bars_accept_matching_provider_symbol(monkeypatch):
    payload = {"symbol": "TEST", "bars": make_daily_bars(1)}
    payload["bars"][0]["S"] = "TEST"
    payload["bars"][0]["symbol"] = "TEST"
    monkeypatch.setattr(market_data, "_get_json", lambda url: payload)
    assert len(market_data.get_recent_daily_bars("TEST")) == 1


@pytest.mark.parametrize("bar", [None, "not a bar", 42, []])
def test_daily_bars_reject_nonobject_bar_before_sorting(monkeypatch, bar):
    monkeypatch.setattr(
        market_data, "_get_json",
        lambda url: {"bars": [bar], "next_page_token": None},
    )
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_recent_daily_bars("TEST")


@pytest.mark.parametrize("offset_days", [-46, 1])
def test_daily_bars_reject_provider_dates_outside_requested_window(
    monkeypatch, offset_days,
):
    # The provider must not silently return old or future sessions for
    # a 45-calendar-day query, even if the response is otherwise well formed.
    bar = make_daily_bars(1)[0]
    day = datetime.now(timezone.utc).date() + timedelta(days=offset_days)
    bar["t"] = f"{day.isoformat()}T04:00:00Z"
    monkeypatch.setattr(
        market_data, "_get_json",
        lambda url: {"bars": [bar], "next_page_token": None},
    )
    with pytest.raises(RuntimeError, match="outside requested window"):
        market_data.get_recent_daily_bars("TEST")


def test_daily_bars_accept_first_requested_utc_date(monkeypatch):
    # Alpaca daily records can be stamped at midnight, earlier than the
    # intraday 'start' clock time on the same calendar date.
    day = (datetime.now(timezone.utc) - timedelta(days=45)).date()
    bar = make_daily_bars(1)[0]
    bar["t"] = f"{day.isoformat()}T04:00:00Z"
    monkeypatch.setattr(
        market_data, "_get_json",
        lambda url: {"bars": [bar], "next_page_token": None},
    )
    assert market_data.get_recent_daily_bars("TEST")[0]["t"] == bar["t"]
