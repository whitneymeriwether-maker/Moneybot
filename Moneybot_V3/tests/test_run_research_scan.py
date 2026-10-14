
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
from backtesting.research_scanner import ResearchResult


def test_default_watchlist_has_no_unverified_market_caps():
    """Watchlist must not contain guessed market caps."""

    assert len(run_research_scan.WATCHLIST) == 5

    for symbol, market_cap in run_research_scan.WATCHLIST:
        assert isinstance(symbol, str)
        assert symbol
        assert market_cap is None


def test_missing_market_caps_are_rejected():
    """Missing market caps must not produce approved stocks."""

    results = run_research_scan.run_scan([
        ("SOFI", None),
        ("F", None),
    ])

    assert len(results) == 2
    assert all(result.qualifies is False for result in results)

    for result in results:
        assert "Verified market capitalization is required" in (
            result.reasons
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


def test_default_scan_does_not_request_market_data(monkeypatch):
    """Unverified stocks must not trigger Alpaca requests."""

    def forbidden_request(symbol, market_cap):
        raise AssertionError(
            "Market data should not be requested "
            "without verified market capitalization"
        )

    monkeypatch.setattr(
        "backtesting.research_scanner.get_stock_candidate",
        forbidden_request,
    )

    results = run_research_scan.run_scan()

    assert len(results) == 5
    assert all(result.qualifies is False for result in results)
