"""Exact whole-share accounting for read-only IEX daily screening.

Synthetic fixtures only; no network, broker connection, or orders.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backtesting import market_data


def _bars(volumes):
    dates = []
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    while len(dates) < len(volumes):
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    return [
        {
            "t": f"{date.isoformat()}T04:00:00Z",
            "o": 12.0, "h": 12.2, "l": 11.8, "c": 12.0,
            "v": volume,
        }
        for date, volume in zip(reversed(dates), volumes)
    ]


@pytest.mark.parametrize("volume", [2**53, 2**53 + 1, float(2**53), 1e308])
def test_unrepresentable_or_unsafe_daily_share_count_fails_closed(volume):
    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        market_data._validate_daily_bars(_bars([volume]), "TEST")


def test_largest_safe_whole_share_count_is_accepted():
    market_data._validate_daily_bars(_bars([2**53 - 1]), "TEST")


def test_daily_volume_average_preserves_small_sessions_next_to_large_one(monkeypatch):
    volumes = [2**53 - 1] + [1] * 19
    monkeypatch.setattr(
        market_data, "get_recent_daily_bars", lambda symbol: _bars(volumes)
    )
    monkeypatch.setattr(
        market_data, "get_latest_quote", lambda symbol: (11.99, 12.0)
    )
    candidate = market_data.get_stock_candidate("TEST", 1_000_000_000)
    assert candidate.average_daily_volume == sum(volumes) / len(volumes)
    naive_float_sum = 0.0
    for volume in volumes:
        naive_float_sum += float(volume)
    assert candidate.average_daily_volume != naive_float_sum / len(volumes)
