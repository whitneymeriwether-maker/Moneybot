"""Fail-closed chronology checks for read-only V3 daily-bar research.

All observations are synthetic. No market APIs, broker calls, or orders.
"""

from datetime import date, timedelta

import pytest

from backtesting import market_data, research_scanner


def daily_bars(count=21):
    day = date(2026, 1, 5)
    bars = []
    while len(bars) < count:
        if day.weekday() < 5:
            bars.append({
                "t": f"{day.isoformat()}T04:00:00Z",
                "o": 12.0, "h": 12.2, "l": 11.8,
                "c": 12.0, "v": 2_000_000,
            })
        day += timedelta(days=1)
    return bars


def hidden_old_reversal():
    bars = daily_bars()
    # The last twenty observations still appear chronologically ordered:
    # a validator that inspects only bars[-20:] misses the earlier reversal.
    bars[0], bars[1] = bars[1], bars[0]
    assert all(
        a["t"] < b["t"] for a, b in zip(bars[-20:], bars[-19:])
    )
    return bars


def test_chronological_daily_history_is_accepted():
    market_data._validate_daily_bars(daily_bars(), "TEST")


def test_reversed_older_daily_bars_are_rejected_before_sampling():
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data._validate_daily_bars(hidden_old_reversal(), "TEST")


def test_candidate_cannot_screen_disordered_daily_history(monkeypatch):
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars",
        lambda symbol: hidden_old_reversal(),
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote",
        lambda symbol: pytest.fail("Do not quote unverified history"),
    )
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data.get_stock_candidate("TEST", 1_000_000_000)


def test_sec_fallback_cannot_estimate_from_disordered_history(monkeypatch):
    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars",
        lambda symbol: hidden_old_reversal(),
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail(
            "Do not estimate market cap from unverified history"
        ),
    )
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        research_scanner._estimate_using_sec("TEST")
