
"""Automated tests for Moneybot V3's research scanner."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import research_scanner
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


def test_qualifying_stock_passes(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        lambda symbol, market_cap: make_candidate(
            symbol=symbol,
            market_cap=market_cap,
        ),
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.symbol == "TEST"
    assert result.qualifies is True
    assert result.reasons == ()


def test_missing_market_cap_rejected(monkeypatch):
    def should_not_be_called(symbol, market_cap):
        raise AssertionError("Market data should not be requested")

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        should_not_be_called,
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert "Verified market capitalization is required" in result.reasons


def test_low_price_rejected(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        lambda symbol, market_cap: make_candidate(
            symbol=symbol,
            price=1.50,
        ),
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Price outside $2-$30 range" in result.reasons


def test_low_volume_rejected(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        lambda symbol, market_cap: make_candidate(
            symbol=symbol,
            average_daily_volume=100_000,
        ),
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert "Insufficient average daily volume" in result.reasons


def test_wide_spread_rejected(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        lambda symbol, market_cap: make_candidate(
            symbol=symbol,
            bid=11.90,
            ask=12.00,
        ),
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
    def fake_candidate(symbol, market_cap):
        if symbol == "LOW":
            return make_candidate(
                symbol=symbol,
                price=1.50,
            )

        return make_candidate(
            symbol=symbol,
            market_cap=market_cap,
        )

    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        fake_candidate,
    )

    results = research_scanner.scan_stocks([
        ("GOOD", 1_000_000_000),
        ("LOW", 1_000_000_000),
        ("NOCAP", None),
    ])

    assert len(results) == 3
    assert results[0].qualifies is True
    assert results[1].qualifies is False
    assert results[2].qualifies is False


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
