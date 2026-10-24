
"""Tests for the Moneybot V3 research scan runner.

All tests use simulated results. No network calls or orders.
"""

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting import run_research_scan
from backtesting import research_scanner
from backtesting.market_cap_data import MarketCapDataError
from backtesting.sec_market_cap import SECMarketCapError
from backtesting.research_scanner import ResearchResult


def test_default_watchlist_has_no_unverified_market_caps():
    """The watchlist must not contain guessed market caps."""

    assert len(run_research_scan.WATCHLIST) == 20

    symbols = []

    for symbol, market_cap in run_research_scan.WATCHLIST:
        assert isinstance(symbol, str)
        assert symbol
        assert market_cap is None
        symbols.append(symbol)

    assert len(symbols) == len(set(symbols))


def test_missing_market_caps_are_rejected(monkeypatch):
    """Failure of both sources must reject each stock."""

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

    for result in results:
        assert any(
            "FMP unavailable" in reason
            for reason in result.reasons
        )
        assert any(
            "SEC estimate unavailable" in reason
            for reason in result.reasons
        )


def test_scan_counts_passed_and_rejected(monkeypatch, capsys):
    """Check the summary with simulated screening results."""

    def fake_scan_stocks(watchlist):
        assert watchlist == [
            ("GOOD", 1_000_000_000),
            ("BAD", 1_000_000_000),
        ]

        return [
            ResearchResult(
                symbol="GOOD",
                qualifies=True,
                reasons=(),
            ),
            ResearchResult(
                symbol="BAD",
                qualifies=False,
                reasons=("Insufficient average daily volume",),
            ),
        ]

    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        fake_scan_stocks,
    )

    results = run_research_scan.run_scan([
        ("GOOD", 1_000_000_000),
        ("BAD", 1_000_000_000),
    ])

    output = capsys.readouterr().out

    assert len(results) == 2
    assert "Stocks requested: 2" in output
    assert "GOOD: PASS" in output
    assert "BAD: REJECT" in output
    assert "Passed: 1" in output
    assert "Rejected: 1" in output


def test_empty_watchlist(monkeypatch, capsys):
    """An empty watchlist should be handled safely."""

    def fake_scan_stocks(watchlist):
        assert watchlist == []
        return []

    monkeypatch.setattr(
        run_research_scan,
        "scan_stocks",
        fake_scan_stocks,
    )

    results = run_research_scan.run_scan([])

    output = capsys.readouterr().out

    assert results == []
    assert "Stocks requested: 0" in output
    assert "Passed: 0" in output
    assert "Rejected: 0" in output


def test_default_scan_does_not_approve_unverified_stocks(
    monkeypatch,
):
    """SEC estimates must never qualify stocks automatically."""

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

    def forbidden_candidate(symbol, market_cap):
        raise AssertionError(
            "Estimated market cap must not enter verified screener"
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
        forbidden_candidate,
    )

    results = run_research_scan.run_scan()

    assert len(results) == 20
    assert all(result.qualifies is False for result in results)
    assert all(
        "ESTIMATE ONLY" in result.reasons[0]
        for result in results
    )
