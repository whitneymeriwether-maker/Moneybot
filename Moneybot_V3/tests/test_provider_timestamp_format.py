"""Offline regression tests for canonical Alpaca quote and bar timestamps."""

from datetime import datetime, timezone

import pytest

from backtesting import market_data


@pytest.mark.parametrize("value,expected", [
    ("2026-10-27T13:30:00Z", "2026-10-27T13:30:00+00:00"),
    ("2026-10-27T13:30:00.123456789Z", "2026-10-27T13:30:00.123456+00:00"),
    ("2026-10-27T19:00:00+05:30", "2026-10-27T13:30:00+00:00"),
    ("2026-10-27T09:30:00-04:00", "2026-10-27T13:30:00+00:00"),
])
def test_canonical_rfc3339_timestamps_are_accepted(value, expected):
    assert market_data._parse_quote_timestamp(value).isoformat() == expected


@pytest.mark.parametrize("value", [
    "2026-W44-2T13:30:00Z",       # ISO week date
    "20261027T133000Z",           # Compact date/time
    "2026-10-27 13:30:00Z",       # Space instead of T
    "2026-10-27T13:30Z",          # Missing seconds
    "2026-10-27T13:30:00+00:00:30",  # Sub-minute timezone offset
    "2026-10-27T13:30:00.1234567890Z",  # Excess precision
    "2026-10-27T13:30:00z",
    "2026-10-27T13:30:00+00:00Z",
    "2026-10-27T13:30:00+24:00",
    "2026-02-30T13:30:00Z",
])
def test_noncanonical_or_invalid_provider_timestamps_fail_closed(value):
    with pytest.raises(RuntimeError, match="Invalid quote timestamp"):
        market_data._parse_quote_timestamp(value)


@pytest.mark.parametrize("value", [None, "", " ", 123, True])
def test_missing_or_nonstring_provider_timestamps_fail_closed(value):
    with pytest.raises(RuntimeError, match="Missing quote timestamp"):
        market_data._parse_quote_timestamp(value)


def test_latest_quote_rejects_fresh_but_noncanonical_timestamp(monkeypatch):
    # A current timestamp is not reliable provider evidence if its format
    # is outside the API's documented RFC 3339 representation.
    compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    monkeypatch.setattr(market_data, "_get_json", lambda _: {
        "quote": {"bp": 11.99, "ap": 12.00, "t": compact}
    })
    with pytest.raises(RuntimeError, match="Invalid quote timestamp"):
        market_data.get_latest_quote("TEST")


def test_daily_download_rejects_noncanonical_provider_bar_timestamp(monkeypatch):
    monkeypatch.setattr(market_data, "_get_json", lambda _: {
        "bars": [{"t": "20261027T133000Z", "o": 10, "h": 11,
                  "l": 9, "c": 10, "v": 1000}],
        "next_page_token": None,
    })
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_recent_daily_bars("TEST")
