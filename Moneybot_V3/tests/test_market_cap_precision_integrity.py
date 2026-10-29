"""Offline precision-integrity tests for independent market-cap providers.

These fixtures contain deliberately unrealistic share/cap counts to expose
IEEE-754 rounding collisions. No external requests or brokerage actions.
"""

import io
import json
from contextlib import nullcontext
from datetime import date, timedelta

import pytest

from backtesting import market_cap_data, sec_market_cap


BIG = 2 ** 53


def _fake_fmp(monkeypatch, values):
    today = date.today().isoformat()
    records = [
        {"symbol": "TEST", "date": today, "marketCap": value}
        for value in values
    ]
    monkeypatch.setenv("FMP_API_KEY", "offline-test-key")
    monkeypatch.setattr(
        market_cap_data,
        "urlopen",
        lambda request, timeout=30: nullcontext(
            io.StringIO(json.dumps(records))
        ),
    )


@pytest.mark.parametrize("values", [
    [BIG, BIG + 1],
    [float(BIG), BIG + 1],
])
def test_distinct_fmp_integer_caps_cannot_merge_when_cast_to_float(
    monkeypatch, values
):
    _fake_fmp(monkeypatch, values)
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Conflicting market capitalization records",
    ):
        market_cap_data.get_market_cap("TEST")


def test_equal_fmp_numeric_values_remain_valid(monkeypatch):
    _fake_fmp(monkeypatch, [BIG, float(BIG)])
    assert market_cap_data.get_market_cap("TEST") == float(BIG)


def _fake_sec(monkeypatch, values):
    observation_date = (date.today() - timedelta(days=30)).isoformat()
    filed_date = (date.today() - timedelta(days=10)).isoformat()
    facts = {
        "cik": 123456,
        "facts": {
            "dei": {
                sec_market_cap.SHARES_TAG: {
                    "units": {
                        "shares": [
                            {"end": observation_date, "filed": filed_date, "val": value}
                            for value in values
                        ]
                    }
                }
            }
        },
    }
    monkeypatch.setattr(
        sec_market_cap, "get_company_cik", lambda symbol: "0000123456"
    )
    monkeypatch.setattr(sec_market_cap, "_request_json", lambda url: facts)


@pytest.mark.parametrize("values", [
    [BIG, BIG + 1],
    [float(BIG), BIG + 1],
])
def test_distinct_sec_share_counts_cannot_merge_when_cast_to_float(
    monkeypatch, values
):
    _fake_sec(monkeypatch, values)
    with pytest.raises(
        sec_market_cap.SECMarketCapError,
        match="Conflicting SEC shares-outstanding data",
    ):
        sec_market_cap.get_reported_shares_outstanding("TEST")


def test_equal_sec_numeric_values_remain_valid(monkeypatch):
    _fake_sec(monkeypatch, [BIG, float(BIG)])
    result = sec_market_cap.get_reported_shares_outstanding("TEST")
    assert result["shares_outstanding"] == float(BIG)
