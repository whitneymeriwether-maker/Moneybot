
"""Tests for Moneybot V3 research scanner.

All external data is simulated. No network requests or trades.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import research_scanner
from backtesting.market_cap_data import MarketCapDataError
from backtesting.sec_market_cap import SECMarketCapError
from backtesting.stock_screener import StockCandidate


def make_candidate(**changes):
    values = {
        "symbol": "TEST",
        "price": 12.00,
        "average_daily_volume": 2_000_000,
        "market_cap": 1_000_000_000,
        "bid": 11.99,
        "ask": 12.00,
    }
    values.update(changes)
    return StockCandidate(**values)


def fake_stock_data(monkeypatch, **changes):
    def get_candidate(symbol, market_cap):
        return make_candidate(
            **{
                **changes,
                "symbol": symbol,
                "market_cap": market_cap,
            }
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        get_candidate,
    )


def fake_fmp_failure(monkeypatch):
    def unavailable(symbol):
        raise MarketCapDataError("Simulated FMP outage")

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        unavailable,
    )


def fake_sec_estimate(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_recent_daily_bars",
        lambda symbol: [{"c": 5.0}],
    )

    monkeypatch.setattr(
        research_scanner,
        "estimate_market_cap",
        lambda symbol, price: {
            "symbol": symbol,
            "shares_outstanding": 100_000_000,
            "observation_date": "2026-08-01",
            "filed_date": "2026-08-10",
            "estimated_market_cap": 500_000_000,
            "estimate_only": True,
        },
    )


def test_qualifying_stock_passes(monkeypatch):
    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.symbol == "TEST"
    assert result.qualifies is True
    assert result.reasons == ()


def test_automatic_market_cap_lookup(monkeypatch):
    requested = []

    def fake_market_cap(symbol):
        requested.append(symbol)
        return 1_000_000_000

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        fake_market_cap,
    )

    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock("test")

    assert requested == ["TEST"]
    assert result.qualifies is True


def test_fmp_failure_uses_sec_estimate(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "ESTIMATE ONLY" in result.reasons[0]
    assert "$500,000,000" in result.reasons[1]
    assert "2026-08-01" in result.reasons[2]
    assert "Simulated FMP outage" in result.reasons[-1]


def test_sec_estimate_cannot_approve_stock(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch)

    def forbidden_candidate(symbol, market_cap):
        raise AssertionError(
            "An SEC estimate must not enter the verified screener"
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        forbidden_candidate,
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False


def test_both_market_cap_sources_fail(monkeypatch):
    fake_fmp_failure(monkeypatch)

    monkeypatch.setattr(
        research_scanner,
        "get_recent_daily_bars",
        lambda symbol: [{"c": 5.0}],
    )

    def unavailable(symbol, price):
        raise SECMarketCapError("Simulated SEC outage")

    monkeypatch.setattr(
        research_scanner,
        "estimate_market_cap",
        unavailable,
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "FMP unavailable" in result.reasons[0]
    assert "SEC estimate unavailable" in result.reasons[1]


def test_missing_fmp_credentials_rejected(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    monkeypatch.setattr(
        research_scanner,
        "get_recent_daily_bars",
        lambda symbol: [],
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "FMP unavailable" in result.reasons[0]


@pytest.mark.parametrize(
    "invalid_cap",
    [
        0,
        -100,
        True,
        float("nan"),
        float("inf"),
        "1000000000",
    ],
)
def test_invalid_market_cap_rejected(monkeypatch, invalid_cap):
    def forbidden_candidate(symbol, market_cap):
        raise AssertionError(
            "Invalid market cap must not trigger Alpaca"
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        forbidden_candidate,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=invalid_cap,
    )

    assert result.qualifies is False
    assert "Invalid market capitalization" in result.reasons


def test_low_price_rejected(monkeypatch):
    fake_stock_data(monkeypatch, price=1.50)

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Price outside $2-$30 range" in result.reasons


def test_low_volume_rejected(monkeypatch):
    fake_stock_data(
        monkeypatch,
        average_daily_volume=100_000,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Insufficient average daily volume" in result.reasons


def test_wide_spread_rejected(monkeypatch):
    fake_stock_data(
        monkeypatch,
        bid=11.90,
        ask=12.00,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Bid-ask spread too wide" in result.reasons


def test_market_data_failure_rejected(monkeypatch):
    def unavailable(symbol, market_cap):
        raise RuntimeError("Simulated Alpaca outage")

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        unavailable,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Simulated Alpaca outage" in result.reasons[0]


def test_invalid_symbol_rejected():
    with pytest.raises(ValueError):
        research_scanner.scan_stock(
            "../BAD",
            market_cap=1_000_000_000,
        )


def test_multiple_stocks(monkeypatch):
    fake_stock_data(monkeypatch)
    fake_sec_estimate(monkeypatch)

    def fake_market_cap(symbol):
        if symbol == "NOCAP":
            raise MarketCapDataError("No market-cap data")
        return 1_000_000_000

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        fake_market_cap,
    )

    results = research_scanner.scan_stocks([
        ("GOOD", 1_000_000_000),
        ("NOCAP", None),
        ("ALSO", None),
    ])

    assert len(results) == 3
    assert results[0].qualifies is True
    assert results[1].qualifies is False
    assert "ESTIMATE ONLY" in results[1].reasons[0]
    assert results[2].qualifies is True


def test_print_results(capsys):
    results = [
        research_scanner.ResearchResult(
            symbol="GOOD",
            qualifies=True,
            reasons=(),
        ),
        research_scanner.ResearchResult(
            symbol="BAD",
            qualifies=False,
            reasons=("Insufficient average daily volume",),
        ),
    ]

    research_scanner.print_results(results)

    output = capsys.readouterr().out

    assert "GOOD: PASS" in output
    assert "BAD: REJECT" in output
    assert "Insufficient average daily volume" in output
