"""FMP provider ticker identity must not use Unicode case-folding.

All requests are simulated and read-only; no provider or brokerage access.
"""

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting import market_cap_data


class FakeResponse:
    def __init__(self, payload):
        self.data = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self.data

    def __exit__(self, exc_type, exc_value, traceback):
        self.data.close()
        return False


def stub_fmp(monkeypatch, records):
    monkeypatch.setenv("FMP_API_KEY", "offline-test-key")
    today = datetime.now(timezone.utc).date().isoformat()
    payload = [{"date": today, **record} for record in records]

    def fake_urlopen(request, timeout=30):
        assert request.get_method() == "GET"
        return FakeResponse(payload)

    monkeypatch.setattr(market_cap_data, "urlopen", fake_urlopen)


@pytest.mark.parametrize("symbol,confusable", [
    ("SPY", "ſPY"),  # Unicode long-s uppercases to ASCII S.
    ("IBM", "ıBM"),  # Unicode dotless-i uppercases to ASCII I.
])
def test_unicode_lookalike_cannot_impersonate_requested_ticker(
    monkeypatch, symbol, confusable
):
    assert confusable.upper() == symbol
    stub_fmp(monkeypatch, [{"symbol": confusable, "marketCap": 500_000_000}])
    with pytest.raises(market_cap_data.MarketCapDataError,
                       match="No matching market-cap record"):
        market_cap_data.get_market_cap(symbol)


@pytest.mark.parametrize("symbol,confusable", [
    ("SPY", "ſPY"),
    ("IBM", "ıBM"),
])
def test_lookalike_record_cannot_poison_real_ascii_ticker(
    monkeypatch, symbol, confusable
):
    stub_fmp(monkeypatch, [
        {"symbol": symbol, "marketCap": 500_000_000},
        {"symbol": confusable, "marketCap": 900_000_000},
    ])
    assert market_cap_data.get_market_cap(symbol) == 500_000_000


def test_ascii_lowercase_provider_symbol_remains_supported(monkeypatch):
    stub_fmp(monkeypatch, [
        {"symbol": "spy", "marketCap": 500_000_000},
        {"symbol": "SPY", "marketCap": 500_000_000},
    ])
    assert market_cap_data.get_market_cap("spy") == 500_000_000
