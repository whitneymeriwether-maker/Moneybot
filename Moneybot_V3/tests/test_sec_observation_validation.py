"""Fail-closed SEC observation-shape/date regression checks (offline only)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting import sec_market_cap


def _observation(*, days_ago=30, shares=100_000_000):
    return {
        "end": (date.today() - timedelta(days=days_ago)).isoformat(),
        "filed": (date.today() - timedelta(days=10)).isoformat(),
        "val": shares,
    }


def _fake_sec(monkeypatch, observations):
    def fetch(url):
        if "company_tickers.json" in url:
            return {"0": {"ticker": "TEST", "cik_str": 123456}}
        if "companyfacts" in url:
            return {
                "cik": 123456,
                "facts": {"dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {"shares": observations}
                    }
                }},
            }
        raise AssertionError(f"Unexpected SEC URL: {url}")

    monkeypatch.setattr(sec_market_cap, "_request_json", fetch)


@pytest.mark.parametrize("observations", [None, {}, "not a list", 42, True, ()])
def test_malformed_observation_container_fails_closed(monkeypatch, observations):
    _fake_sec(monkeypatch, observations)
    with pytest.raises(sec_market_cap.SECMarketCapError, match="Malformed SEC shares"):
        sec_market_cap.get_reported_shares_outstanding("TEST")


@pytest.mark.parametrize("field", ["end", "filed"])
@pytest.mark.parametrize("format_kind", ["compact", "week", "date_object", "space"])
def test_noncanonical_sec_dates_are_not_accepted(monkeypatch, field, format_kind):
    invalid = _observation()
    parsed = date.fromisoformat(invalid[field])
    if format_kind == "compact":
        invalid[field] = parsed.strftime("%Y%m%d")
    elif format_kind == "week":
        invalid[field] = parsed.strftime("%G-W%V-%u")
    elif format_kind == "date_object":
        invalid[field] = parsed
    else:
        invalid[field] += " "
    _fake_sec(monkeypatch, [invalid])
    with pytest.raises(sec_market_cap.SECMarketCapError, match="No recent SEC shares"):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_invalid_newer_date_does_not_displace_valid_older_fact(monkeypatch):
    valid = _observation(days_ago=60, shares=75_000_000)
    malformed = _observation(days_ago=20, shares=125_000_000)
    malformed["end"] = malformed["end"].replace("-", "")
    _fake_sec(monkeypatch, [valid, malformed])
    report = sec_market_cap.get_reported_shares_outstanding("TEST")
    assert report["shares_outstanding"] == 75_000_000
    assert report["observation_date"] == valid["end"]
