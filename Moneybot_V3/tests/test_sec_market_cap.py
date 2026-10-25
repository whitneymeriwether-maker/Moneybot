
"""Tests for Moneybot V3 SEC shares-outstanding research.

All SEC responses are simulated. No network requests.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import sec_market_cap


def make_observation(shares=100_000_000, days_ago=30):
    observed = date.today() - timedelta(days=days_ago)
    filed = date.today() - timedelta(days=10)

    return {
        "end": observed.isoformat(),
        "filed": filed.isoformat(),
        "val": shares,
    }


def configure_fake_sec(monkeypatch, observations):
    """Replace SEC network calls with simulated responses."""

    def fake_request_json(url):
        if "company_tickers.json" in url:
            return {
                "0": {
                    "ticker": "TEST",
                    "cik_str": 123456,
                    "title": "Test Corporation",
                }
            }

        if "companyfacts" in url:
            return {
                "facts": {
                    "dei": {
                        "EntityCommonStockSharesOutstanding": {
                            "units": {
                                "shares": observations,
                            }
                        }
                    }
                }
            }

        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(
        sec_market_cap,
        "_request_json",
        fake_request_json,
    )


def test_company_cik_lookup(monkeypatch):
    configure_fake_sec(monkeypatch, [])

    assert (
        sec_market_cap.get_company_cik("test")
        == "0000123456"
    )


def test_recent_shares_outstanding(monkeypatch):
    configure_fake_sec(
        monkeypatch,
        [make_observation()],
    )

    result = (
        sec_market_cap.get_reported_shares_outstanding("TEST")
    )

    assert result["shares_outstanding"] == 100_000_000
    assert result["source"] == "SEC EDGAR"


def test_market_cap_estimate(monkeypatch):
    configure_fake_sec(
        monkeypatch,
        [make_observation()],
    )

    result = sec_market_cap.estimate_market_cap(
        "TEST",
        5.0,
    )

    assert result["estimated_market_cap"] == 500_000_000
    assert result["estimate_only"] is True


def test_stale_shares_rejected(monkeypatch):
    configure_fake_sec(
        monkeypatch,
        [make_observation(days_ago=200)],
    )

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="No recent SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_missing_shares_rejected(monkeypatch):
    configure_fake_sec(monkeypatch, [])

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="No recent SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_invalid_share_price_rejected(monkeypatch):
    with pytest.raises(ValueError):
        sec_market_cap.estimate_market_cap("TEST", -1)


def test_unknown_symbol_rejected(monkeypatch):
    configure_fake_sec(monkeypatch, [])

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="No SEC company identifier",
    ):
        sec_market_cap.get_company_cik("UNKNOWN")


def test_newest_observation_selected(monkeypatch):
    configure_fake_sec(
        monkeypatch,
        [
            make_observation(shares=80_000_000, days_ago=90),
            make_observation(shares=120_000_000, days_ago=20),
        ],
    )

    result = (
        sec_market_cap.get_reported_shares_outstanding("TEST")
    )

    assert result["shares_outstanding"] == 120_000_000


def test_oversized_sec_share_count_is_skipped(monkeypatch):
    configure_fake_sec(monkeypatch, [
        make_observation(shares=10 ** 400, days_ago=20),
        make_observation(shares=75_000_000, days_ago=60),
    ])
    result = sec_market_cap.get_reported_shares_outstanding("TEST")
    assert result["shares_outstanding"] == 75_000_000


def test_only_oversized_sec_shares_fail_closed(monkeypatch):
    configure_fake_sec(monkeypatch, [make_observation(shares=10 ** 400)])
    with pytest.raises(sec_market_cap.SECMarketCapError,
                       match="No recent SEC shares-outstanding data"):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_oversized_share_price_fails_closed():
    with pytest.raises(ValueError, match="Share price must be positive"):
        sec_market_cap.estimate_market_cap("TEST", 10 ** 400)


def test_overflowing_sec_market_cap_estimate_fails_closed(monkeypatch):
    configure_fake_sec(monkeypatch, [make_observation(shares=1e308)])
    with pytest.raises(sec_market_cap.SECMarketCapError,
                       match="Non-finite SEC market-cap estimate"):
        sec_market_cap.estimate_market_cap("TEST", 1e308)
