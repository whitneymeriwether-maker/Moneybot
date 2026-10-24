
"""Tests for the Moneybot V3 research scan runner.

All tests use simulated data.
No network requests or brokerage orders.
"""

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import research_scanner, run_research_scan
from backtesting.market_cap_data import MarketCapDataError
from backtesting.sec_market_cap import SECMarketCapError
from backtesting.research_scanner import ResearchResult


def test_default_watchlist():
    assert len(run_research_scan.WATCHLIST) == 20

    symbols = []

    for symbol, market_cap in run_research_scan.WATCHLIST:
        assert isinstance(symbol, str)
        assert symbol
        assert market_cap is None
        symbols.append(symbol)

    assert len(symbols) == len(set(symbols))


def test_missing_market_caps_are_unverified(monkeypatch):
    def unavailable_fmp(symbol):
        raise MarketCapDataError("Simulated FMP outage")

    def unavailable_sec(symbol):
        raise SECMarketCapError("Simulated SEC outage")

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        unavailable_fmp,
    )
    monkeypatch.setattr(
        research_scanner,
        "_estimate_using_sec",
        unavailable_sec,
    )

    results = run_research_scan.run_scan([
        ("SOFI", None),
        ("F", None),
    ])

    assert len(results) == 2
    assert all(result.qualifies is False for result in results)
    assert all(result.provisional is False for result in results)
    assert all(result.data_unverified is True for result in results)


def test_all_four_classifications(monkeypatch, capsys):
    def fake_scan_stocks(watchlist):
        assert len(watchlist) == 4

        return [
            ResearchResult(
                symbol="GOOD",
                qualifies=True,
                reasons=(),
            ),
            ResearchResult(
                symbol="MAYBE",
                qualifies=False,
                provisional=True,
                reasons=("Market cap is estimated",),
            ),
            ResearchResult(
                symbol="UNKNOWN",
                qualifies=False,
                data_unverified=True,
                reasons=("IEX volume is inconclusive",),
            ),
            ResearchResult(
                symbol="BAD",
                qualifies=False,
                reasons=("Price outside $2-$30 range",),
            ),
        ]

    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        fake_scan_stocks,
    )

    results = run_research_scan.run_scan([
        ("GOOD", None),
        ("MAYBE", None),
        ("UNKNOWN", None),
        ("BAD", None),
    ])

    output = capsys.readouterr().out

    assert len(results) == 4

    assert "GOOD: PASS" in output
    assert "MAYBE: PROVISIONAL" in output
    assert "UNKNOWN: DATA UNVERIFIED" in output
    assert "BAD: REJECT" in output

    assert "Passed: 1" in output
    assert "Provisional: 1" in output
    assert "Data unverified: 1" in output
    assert "Rejected: 1" in output


def test_provisional_not_counted_as_pass(monkeypatch, capsys):
    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        lambda watchlist: [
            ResearchResult(
                symbol="MAYBE",
                qualifies=False,
                provisional=True,
                reasons=("Market cap not verified",),
            )
        ],
    )

    results = run_research_scan.run_scan([
        ("MAYBE", None),
    ])

    output = capsys.readouterr().out

    assert len(results) == 1
    assert results[0].qualifies is False
    assert results[0].provisional is True

    assert "Passed: 0" in output
    assert "Provisional: 1" in output
    assert "Data unverified: 0" in output
    assert "Rejected: 0" in output


def test_unverified_not_counted_as_pass(monkeypatch, capsys):
    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        lambda watchlist: [
            ResearchResult(
                symbol="UNKNOWN",
                qualifies=False,
                data_unverified=True,
                reasons=("Market data unavailable",),
            )
        ],
    )

    results = run_research_scan.run_scan([
        ("UNKNOWN", None),
    ])

    output = capsys.readouterr().out

    assert len(results) == 1
    assert results[0].qualifies is False
    assert results[0].data_unverified is True

    assert "Passed: 0" in output
    assert "Provisional: 0" in output
    assert "Data unverified: 1" in output
    assert "Rejected: 0" in output


def test_empty_watchlist(monkeypatch, capsys):
    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        lambda watchlist: [],
    )

    results = run_research_scan.run_scan([])

    output = capsys.readouterr().out

    assert results == []
    assert "Stocks requested: 0" in output
    assert "Passed: 0" in output
    assert "Provisional: 0" in output
    assert "Data unverified: 0" in output
    assert "Rejected: 0" in output


def test_default_scan_does_not_approve_sec_estimates(monkeypatch):
    def unavailable_fmp(symbol):
        raise MarketCapDataError("Simulated FMP outage")

    def estimated_sec(symbol):
        return {
            "symbol": symbol,
            "shares_outstanding": 100_000_000,
            "observation_date": "2026-08-01",
            "filed_date": "2026-08-10",
            "estimated_market_cap": 500_000_000,
            "estimate_only": True,
        }

    def fake_candidate(symbol, market_cap):
        from backtesting.stock_screener import StockCandidate

        return StockCandidate(
            symbol=symbol,
            price=12.00,
            average_daily_volume=2_000_000,
            market_cap=market_cap,
            bid=11.99,
            ask=12.00,
        )

    monkeypatch.setattr(
        research_scanner,
        "get_market_cap",
        unavailable_fmp,
    )
    monkeypatch.setattr(
        research_scanner,
        "_estimate_using_sec",
        estimated_sec,
    )
    monkeypatch.setattr(
        research_scanner,
        "get_stock_candidate",
        fake_candidate,
    )

    results = run_research_scan.run_scan()

    assert len(results) == 20
    assert all(result.qualifies is False for result in results)
    assert all(result.provisional is True for result in results)
    assert all(result.data_unverified is False for result in results)
