
"""Tests for Moneybot V3 market capitalization data.

All API responses are simulated. No network requests.
"""

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import market_cap_data


class FakeResponse:
    """Simulate an HTTP response from FMP."""

    def __init__(self, payload):
        self.stream = io.BytesIO(
            json.dumps(payload).encode("utf-8")
        )

    def __enter__(self):
        return self.stream

    def __exit__(self, exc_type, exc_value, traceback):
        self.stream.close()
        return False


def configure_fake_api(monkeypatch, payload, *, add_current_date=True):
    """Set fake credentials and replace the network request.

    Older test fixtures omit the provider's date; add today's date unless
    the test explicitly exercises a missing or malformed observation date.
    """
    if add_current_date and isinstance(payload, list):
        today = datetime.now(timezone.utc).date().isoformat()
        payload = [
            {"date": today, **record} if isinstance(record, dict) else record
            for record in payload
        ]

    monkeypatch.setenv("FMP_API_KEY", "fake-test-key")

    def fake_urlopen(request, timeout=30):
        assert request.get_method() == "GET"
        assert "market-capitalization" in request.full_url
        assert "apikey=fake-test-key" in request.full_url

        return FakeResponse(payload)

    monkeypatch.setattr(
        market_cap_data,
        "urlopen",
        fake_urlopen,
    )


def test_valid_market_cap(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000}],
    )

    result = market_cap_data.get_market_cap("TEST")

    assert result == 1_500_000_000


def test_symbol_normalization(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 500_000_000}],
    )

    result = market_cap_data.get_market_cap("test")

    assert result == 500_000_000


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Missing FMP_API_KEY",
    ):
        market_cap_data.get_market_cap("TEST")


def test_empty_response_rejected(monkeypatch):
    configure_fake_api(monkeypatch, [])

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="No market-cap records returned",
    ):
        market_cap_data.get_market_cap("TEST")


def test_wrong_symbol_rejected(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "OTHER", "marketCap": 1_000_000_000}],
    )

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="No matching market-cap record",
    ):
        market_cap_data.get_market_cap("TEST")


@pytest.mark.parametrize(
    "invalid_value",
    [
        None,
        0,
        -100,
        True,
        "1000000000",
        float("nan"),
        float("inf"),
        10 ** 400,
    ],
)
def test_invalid_market_cap_rejected(monkeypatch, invalid_value):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": invalid_value}],
    )

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Invalid market capitalization",
    ):
        market_cap_data.get_market_cap("TEST")


def test_network_failure_rejected(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "fake-test-key")

    def fake_urlopen(request, timeout=30):
        raise URLError("Simulated connection failure")

    monkeypatch.setattr(
        market_cap_data,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="FMP network connection failed",
    ):
        market_cap_data.get_market_cap("TEST")


def test_http_error_rejected_without_exposing_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "fake-test-key")

    def fake_urlopen(request, timeout=30):
        raise HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        market_cap_data,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="FMP HTTP 403 for TEST",
    ) as error:
        market_cap_data.get_market_cap("TEST")

    assert "fake-test-key" not in str(error.value)


def test_invalid_symbol_rejected():
    with pytest.raises(ValueError):
        market_cap_data.get_market_cap("../BAD")


def test_identical_duplicate_market_cap_records_are_accepted(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [
            {"symbol": "TEST", "marketCap": 1_500_000_000},
            {"symbol": "test", "marketCap": 1_500_000_000},
        ],
    )
    assert market_cap_data.get_market_cap("TEST") == 1_500_000_000


def test_conflicting_market_cap_records_are_rejected(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [
            {"symbol": "TEST", "marketCap": 1_500_000_000},
            {"symbol": "TEST", "marketCap": 100_000_000},
        ],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Conflicting market capitalization records",
    ):
        market_cap_data.get_market_cap("TEST")


@pytest.mark.parametrize("invalid", [None, -1, True, "1000000000", 10 ** 400])
def test_invalid_duplicate_cannot_hide_behind_valid_record(monkeypatch, invalid):
    configure_fake_api(
        monkeypatch,
        [
            {"symbol": "TEST", "marketCap": 1_500_000_000},
            {"symbol": "TEST", "marketCap": invalid},
        ],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Invalid market capitalization",
    ):
        market_cap_data.get_market_cap("TEST")


def test_other_symbols_do_not_conflict_with_requested_market_cap(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [
            {"symbol": "OTHER", "marketCap": 100_000_000},
            {"symbol": "TEST", "marketCap": 1_500_000_000},
        ],
    )
    assert market_cap_data.get_market_cap("TEST") == 1_500_000_000


def test_missing_fmp_observation_date_is_unverified(monkeypatch):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000}],
        add_current_date=False,
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Missing or invalid market-cap date",
    ):
        market_cap_data.get_market_cap("TEST")


@pytest.mark.parametrize("invalid_date", [
    None, True, "", "2026-2-3", "2026-02-30", "not a date",
])
def test_invalid_fmp_observation_dates_are_rejected(monkeypatch, invalid_date):
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000, "date": invalid_date}],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Missing or invalid market-cap date",
    ):
        market_cap_data.get_market_cap("TEST")


@pytest.mark.parametrize("age_days", [8, 30])
def test_stale_fmp_market_cap_does_not_pass_screening(monkeypatch, age_days):
    old = (datetime.now(timezone.utc).date() - timedelta(days=age_days)).isoformat()
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000, "date": old}],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Stale or future market-cap date",
    ):
        market_cap_data.get_market_cap("TEST")


def test_future_fmp_market_cap_date_is_rejected(monkeypatch):
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000, "date": future}],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Stale or future market-cap date",
    ):
        market_cap_data.get_market_cap("TEST")


def test_recent_fmp_market_cap_date_is_accepted(monkeypatch):
    last_week = (
        datetime.now(timezone.utc).date()
        - market_cap_data.MAX_MARKET_CAP_AGE
    ).isoformat()
    configure_fake_api(
        monkeypatch,
        [{"symbol": "TEST", "marketCap": 1_500_000_000, "date": last_week}],
    )
    assert market_cap_data.get_market_cap("TEST") == 1_500_000_000


def test_conflicting_fmp_record_dates_rejected_even_with_same_cap(monkeypatch):
    today = datetime.now(timezone.utc).date()
    configure_fake_api(
        monkeypatch,
        [
            {"symbol": "TEST", "marketCap": 1_500_000_000, "date": today.isoformat()},
            {"symbol": "TEST", "marketCap": 1_500_000_000, "date": (today - timedelta(days=1)).isoformat()},
        ],
    )
    with pytest.raises(
        market_cap_data.MarketCapDataError,
        match="Conflicting market-cap record dates",
    ):
        market_cap_data.get_market_cap("TEST")
