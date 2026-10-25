
"""Tests for Moneybot V3 research classifications.

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


def fake_sec_estimate(monkeypatch, market_cap=500_000_000):
    monkeypatch.setattr(
        research_scanner,
        "_estimate_using_sec",
        lambda symbol: {
            "symbol": symbol,
            "shares_outstanding": 100_000_000,
            "observation_date": "2026-08-01",
            "filed_date": "2026-08-10",
            "estimated_market_cap": market_cap,
            "estimate_only": True,
        },
    )


def test_verified_stock_passes(monkeypatch):
    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is True
    assert result.provisional is False
    assert result.data_unverified is False
    assert result.reasons == ()


def test_automatic_fmp_lookup(monkeypatch):
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
    assert result.data_unverified is False


def test_sec_estimate_is_provisional(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch)
    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert result.provisional is True
    assert result.data_unverified is False
    assert "not verified" in result.reasons[0]


def test_sec_estimate_wide_iex_spread_is_unverified(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch)
    fake_stock_data(monkeypatch, bid=11.50, ask=12.00)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert any("NBBO spread not verified" in r for r in result.reasons)
    assert any("SEC/Alpaca estimate" in r for r in result.reasons)


def test_sec_estimate_outside_market_cap_range(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch, market_cap=100_000_000)
    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert result.provisional is False
    assert "Market cap outside research range" in result.reasons


def test_both_market_cap_sources_unavailable(monkeypatch):
    fake_fmp_failure(monkeypatch)

    def unavailable(symbol):
        raise SECMarketCapError("Simulated SEC outage")

    monkeypatch.setattr(
        research_scanner,
        "_estimate_using_sec",
        unavailable,
    )

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert "FMP unavailable" in result.reasons[0]
    assert "SEC estimate unavailable" in result.reasons[1]


@pytest.mark.parametrize(
    "invalid_cap",
    [
        0,
        -100,
        True,
        float("nan"),
        float("inf"),
        10 ** 400,
        "1000000000",
    ],
)
def test_invalid_market_cap_unverified(invalid_cap):
    result = research_scanner.scan_stock(
        "TEST",
        market_cap=invalid_cap,
    )

    assert result.qualifies is False
    assert result.data_unverified is True
    assert "Invalid market capitalization" in result.reasons


def test_low_price_rejected(monkeypatch):
    fake_stock_data(monkeypatch, price=1.50)

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert result.data_unverified is False
    assert "Price outside $2-$30 range" in result.reasons


def test_low_iex_volume_is_unverified(monkeypatch):
    fake_stock_data(
        monkeypatch,
        average_daily_volume=100_000,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert any(
        "IEX" in reason
        for reason in result.reasons
    )


def test_wide_iex_spread_is_unverified(monkeypatch):
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
    assert result.provisional is False
    assert result.data_unverified is True
    assert any("NBBO spread not verified" in r for r in result.reasons)


def test_low_iex_volume_and_wide_spread_both_unverified(monkeypatch):
    fake_stock_data(
        monkeypatch,
        average_daily_volume=100_000,
        bid=11.90,
        ask=12.00,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert result.data_unverified is True
    assert any("consolidated volume not verified" in r for r in result.reasons)
    assert any("NBBO spread not verified" in r for r in result.reasons)


def test_confirmed_price_failure_overrides_wide_iex_spread(monkeypatch):
    fake_stock_data(
        monkeypatch,
        price=1.50,
        bid=1.45,
        ask=1.50,
    )

    result = research_scanner.scan_stock(
        "TEST",
        market_cap=1_000_000_000,
    )

    assert result.qualifies is False
    assert result.data_unverified is False
    assert result.reasons == ("Price outside $2-$30 range",)


@pytest.mark.parametrize(
    'invalid_quote', [
        {'average_daily_volume': float('nan')},
        {'bid': 0},
        {'bid': 12.10, 'ask': 12.00},
        {'bid': 12.00, 'ask': 12.00},
    ],
)
def test_malformed_market_data_is_unverified(monkeypatch, invalid_quote):
    fake_stock_data(monkeypatch, **invalid_quote)
    result = research_scanner.scan_stock('TEST', market_cap=1_000_000_000)
    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert result.reasons


def test_confirmed_price_failure_overrides_invalid_quote(monkeypatch):
    fake_stock_data(monkeypatch, price=1.50, bid=0)
    result = research_scanner.scan_stock('TEST', market_cap=1_000_000_000)
    assert result.qualifies is False
    assert result.data_unverified is False
    assert result.reasons == ('Price outside $2-$30 range',)


def test_market_data_failure_unverified(monkeypatch):
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
    assert result.data_unverified is True
    assert "Simulated Alpaca outage" in result.reasons[0]


def test_invalid_symbol():
    with pytest.raises(ValueError):
        research_scanner.scan_stock(
            "../BAD",
            market_cap=1_000_000_000,
        )


def test_multiple_stocks(monkeypatch):
    fake_stock_data(monkeypatch)
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch)

    results = research_scanner.scan_stocks([
        ("VERIFIED", 1_000_000_000),
        ("ESTIMATED", None),
    ])

    assert len(results) == 2
    assert results[0].qualifies is True
    assert results[1].qualifies is False
    assert results[1].provisional is True


def test_print_results(capsys):
    results = [
        research_scanner.ResearchResult(
            symbol="GOOD",
            qualifies=True,
            reasons=(),
        ),
        research_scanner.ResearchResult(
            symbol="MAYBE",
            qualifies=False,
            provisional=True,
            reasons=("Market cap not verified",),
        ),
        research_scanner.ResearchResult(
            symbol="UNKNOWN",
            qualifies=False,
            data_unverified=True,
            reasons=("IEX volume is inconclusive",),
        ),
        research_scanner.ResearchResult(
            symbol="BAD",
            qualifies=False,
            reasons=("Price outside $2-$30 range",),
        ),
    ]

    research_scanner.print_results(results)

    output = capsys.readouterr().out

    assert "GOOD: PASS" in output
    assert "MAYBE: PROVISIONAL" in output
    assert "UNKNOWN: DATA UNVERIFIED" in output
    assert "BAD: REJECT" in output
