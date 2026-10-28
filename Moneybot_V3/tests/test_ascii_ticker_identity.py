"""Offline ASCII ticker identity checks for V3 research providers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.download_data import validate_symbol
from backtesting import sec_market_cap


@pytest.mark.parametrize("invalid", [
    None, 123, True, b"SPY", ["SPY"], {"symbol": "SPY"},
    "ſPY", "ıBM", "ß", "ＳＰＹ", "\u00a0SPY",
])
def test_symbol_validator_rejects_nontext_and_unicode_lookalikes(invalid):
    with pytest.raises(ValueError, match="Invalid stock symbol"):
        validate_symbol(invalid)


@pytest.mark.parametrize("invalid", [None, b"SPY", "ſPY", "ıBM", "ß"])
def test_sec_lookup_rejects_invalid_symbol_before_network(monkeypatch, invalid):
    def no_network(url):
        raise AssertionError("Invalid ticker must not trigger SEC request")
    monkeypatch.setattr(sec_market_cap, "_request_json", no_network)
    with pytest.raises(ValueError, match="Invalid stock symbol"):
        sec_market_cap.get_company_cik(invalid)


def test_sec_lookup_accepts_dotted_class_share_symbol(monkeypatch):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "BRK.B", "cik_str": 123456},
    })
    assert sec_market_cap.get_company_cik(" brk.b ") == "0000123456"


def test_sec_lookup_does_not_match_unicode_provider_ticker(monkeypatch):
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: {
        "0": {"ticker": "ſPY", "cik_str": 123456},
    })
    with pytest.raises(sec_market_cap.SECMarketCapError,
                       match="No SEC company identifier"):
        sec_market_cap.get_company_cik("SPY")


def test_sec_report_returns_canonical_symbol(monkeypatch):
    from datetime import date, timedelta
    def fake_sec(url):
        if "company_tickers" in url:
            return {"0": {"ticker": "BRK.B", "cik_str": 123456}}
        return {"cik": 123456, "facts": {"dei": {
            sec_market_cap.SHARES_TAG: {"units": {"shares": [{
                "end": (date.today() - timedelta(days=30)).isoformat(),
                "filed": (date.today() - timedelta(days=10)).isoformat(),
                "val": 100_000_000,
            }]}}
        }}}
    monkeypatch.setattr(sec_market_cap, "_request_json", fake_sec)
    report = sec_market_cap.get_reported_shares_outstanding(" brk.b ")
    assert report["symbol"] == "BRK.B"
    assert report["shares_outstanding"] == 100_000_000
