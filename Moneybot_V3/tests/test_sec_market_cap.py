
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


def test_sec_shares_ignore_filing_before_observation(monkeypatch):
    # A filing date before its purported shares observation is impossible.
    valid = make_observation(shares=75_000_000, days_ago=60)
    impossible = make_observation(shares=150_000_000, days_ago=5)
    impossible["filed"] = (date.today() - timedelta(days=10)).isoformat()
    configure_fake_sec(monkeypatch, [valid, impossible])

    result = sec_market_cap.get_reported_shares_outstanding("TEST")

    assert result["shares_outstanding"] == 75_000_000
    assert result["observation_date"] == valid["end"]


def test_sec_shares_fail_closed_if_all_filings_predate_observations(monkeypatch):
    impossible = make_observation(days_ago=5)
    impossible["filed"] = (date.today() - timedelta(days=10)).isoformat()
    configure_fake_sec(monkeypatch, [impossible])

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="No recent SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_sec_shares_reject_conflicting_same_date_facts(monkeypatch):
    first = make_observation(shares=100_000_000)
    conflicting = make_observation(shares=120_000_000)
    configure_fake_sec(monkeypatch, [first, conflicting])

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Conflicting SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_sec_shares_accept_identical_duplicate_facts(monkeypatch):
    observation = make_observation(shares=100_000_000)
    configure_fake_sec(monkeypatch, [observation, dict(observation)])

    result = sec_market_cap.get_reported_shares_outstanding("TEST")

    assert result["shares_outstanding"] == 100_000_000


def test_sec_shares_reject_conflict_at_latest_date_even_with_older_valid_fact(
    monkeypatch,
):
    older = make_observation(shares=80_000_000, days_ago=60)
    recent_a = make_observation(shares=100_000_000, days_ago=20)
    recent_b = make_observation(shares=120_000_000, days_ago=20)
    configure_fake_sec(monkeypatch, [older, recent_a, recent_b])

    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Conflicting SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_sec_ticker_directory_rejects_conflicting_company_ids(monkeypatch):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "TEST", "cik_str": 123456},
        "1": {"ticker": "test", "cik_str": 999999},
    })
    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Conflicting SEC company identifiers",
    ):
        sec_market_cap.get_company_cik("TEST")


def test_sec_ticker_directory_accepts_equivalent_duplicate_ids(monkeypatch):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "TEST", "cik_str": 123456},
        "1": {"ticker": "test", "cik_str": "0000123456"},
        "2": {"ticker": "OTHER", "cik_str": "invalid"},
    })
    assert sec_market_cap.get_company_cik("TEST") == "0000123456"


@pytest.mark.parametrize(
    "bad_cik",
    [None, 0, -1, True, 1.5, "abc", "123.0", "0000000000",
     "12345678901", 10 ** 20, "１２３"],
)
def test_sec_ticker_directory_rejects_invalid_matching_cik(
    monkeypatch, bad_cik,
):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "TEST", "cik_str": bad_cik},
    })
    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Invalid SEC company identifier",
    ):
        sec_market_cap.get_company_cik("TEST")


def test_sec_ticker_directory_rejects_invalid_later_duplicate(monkeypatch):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "TEST", "cik_str": 123456},
        "1": {"ticker": "TEST", "cik_str": None},
    })
    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Invalid SEC company identifier",
    ):
        sec_market_cap.get_company_cik("TEST")
