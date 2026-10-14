
"""Automated tests for Moneybot V3's research scanner.

All market data is simulated. No network requests or trades.
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
from backtesting.stock_screener import StockCandidate


def make_candidate(**changes):
    """Create a stock that passes the research filters."""

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
    """Replace Alpaca market data with simulated values."""

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
    """Missing market cap should trigger the FMP provider."""

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
    assert result.symbol == "TEST"
    assert result.qualifies is True


def test_market_cap_provider_failure_rejected(monkeypatch):
    """Failed FMP lookup must not approve a stock."""

    def unavailable(symbol):
        raise MarketCapDataError("Simulated FMP outage")

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        unavailable,
    )

    def forbidden_stock_request(symbol, market_cap):
        raise AssertionError(
            "Alpaca should not be called after FMP failure"
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        forbidden_stock_request,
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "Verified market capitalization is required" in (
        result.reasons[0]
    )
    assert "Simulated FMP outage" in result.reasons[0]


def test_missing_fmp_credentials_rejected(monkeypatch):
    """Missing API credentials should fail safely."""

    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "Verified market capitalization is required" in (
        result.reasons[0]
    )


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
    def forbidden_stock_request(symbol, market_cap):
        raise AssertionError(
            "Invalid market cap must not trigger Alpaca"
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        forbidden_stock_request,
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
