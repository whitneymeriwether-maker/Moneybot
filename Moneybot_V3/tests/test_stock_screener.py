
"""Automated tests for the Moneybot V3 stock screener."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting.stock_screener import (
    StockCandidate,
    screen_stock,
    screen_stocks,
)


def make_candidate(**changes):
    """Create a qualifying stock with optional changes."""

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


def test_qualifying_stock_passes():
    result = screen_stock(make_candidate())

    assert result.qualifies is True
    assert result.reasons == ()


@pytest.mark.parametrize(
    "price",
    [1.99, 30.01, 0, -5],
)
def test_price_outside_range_fails(price):
    result = screen_stock(make_candidate(price=price))

    assert result.qualifies is False
    assert "Price outside $2-$30 range" in result.reasons


@pytest.mark.parametrize(
    "price",
    [2.00, 30.00],
)
def test_price_boundaries_pass(price):
    result = screen_stock(make_candidate(price=price))

    assert result.qualifies is True


def test_insufficient_volume_fails():
    result = screen_stock(
        make_candidate(average_daily_volume=999_999)
    )

    assert result.qualifies is False
    assert "Insufficient average daily volume" in result.reasons


def test_market_cap_too_small_fails():
    result = screen_stock(
        make_candidate(market_cap=299_999_999)
    )

    assert result.qualifies is False
    assert "Market cap outside research range" in result.reasons


def test_market_cap_too_large_fails():
    result = screen_stock(
        make_candidate(market_cap=10_000_000_001)
    )

    assert result.qualifies is False
    assert "Market cap outside research range" in result.reasons


def test_wide_bid_ask_spread_fails():
    result = screen_stock(
        make_candidate(bid=11.90, ask=12.00)
    )

    assert result.qualifies is False
    assert "Bid-ask spread too wide" in result.reasons


def test_negative_bid_fails():
    result = screen_stock(
        make_candidate(bid=-1.00)
    )

    assert result.qualifies is False
    assert "Invalid bid or ask" in result.reasons


def test_crossed_quote_fails():
    result = screen_stock(
        make_candidate(bid=12.01, ask=12.00)
    )

    assert result.qualifies is False
    assert "Ask price below bid price" in result.reasons


def test_missing_symbol_fails():
    result = screen_stock(
        make_candidate(symbol="")
    )

    assert result.qualifies is False
    assert "Missing stock symbol" in result.reasons


@pytest.mark.parametrize(
    "invalid_price",
    [float("nan"), float("inf"), float("-inf")],
)
def test_invalid_numeric_data_fails(invalid_price):
    result = screen_stock(
        make_candidate(price=invalid_price)
    )

    assert result.qualifies is False
    assert "Invalid numeric market data" in result.reasons


def test_multiple_stocks():
    candidates = [
        make_candidate(symbol="GOOD"),
        make_candidate(symbol="CHEAP", price=1.50),
        make_candidate(symbol="THIN", average_daily_volume=100),
    ]

    results = screen_stocks(candidates)

    assert len(results) == 3
    assert results[0].qualifies is True
    assert results[1].qualifies is False
    assert results[2].qualifies is False


def test_multiple_rejection_reasons():
    result = screen_stock(
        make_candidate(
            price=1.00,
            average_daily_volume=100,
            market_cap=50_000_000,
            bid=0.90,
            ask=1.00,
        )
    )

    assert result.qualifies is False
    assert len(result.reasons) == 4
