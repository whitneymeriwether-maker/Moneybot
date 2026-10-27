
"""Tests for Moneybot V3 research classifications.

All market data is simulated. No network requests or trades.
"""

import sys
from datetime import datetime, timedelta, timezone
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
    assert result.data_unverified is True
    assert any("estimated market cap outside research range" in reason
               for reason in result.reasons)
    assert any("verified market cap unavailable" in reason
               for reason in result.reasons)


def test_verified_market_cap_outside_range_is_rejected(monkeypatch):
    fake_stock_data(monkeypatch)

    result = research_scanner.scan_stock(
        "TEST", market_cap=100_000_000,
    )

    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is False
    assert result.reasons == ("Market cap outside research range",)


def test_confirmed_price_failure_overrides_out_of_range_sec_estimate(monkeypatch):
    fake_fmp_failure(monkeypatch)
    fake_sec_estimate(monkeypatch, market_cap=100_000_000)
    fake_stock_data(monkeypatch, price=1.50)

    result = research_scanner.scan_stock("TEST")

    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is False
    assert "Price outside $2-$30 range" in result.reasons


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


def test_overflowed_quote_is_unverified_not_approved(monkeypatch):
    # A finite bid and ask can produce an infinite computed midpoint.
    fake_stock_data(monkeypatch, bid=1e308, ask=1.01e308)
    result = research_scanner.scan_stock(
        "TEST", market_cap=1_000_000_000,
    )
    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert "Invalid numeric market data" in result.reasons


def make_sec_fallback_bars(age_days=0, count=20):
    """Generate recent weekday OHLCV bars without network access."""
    dates = []
    day = datetime.now(timezone.utc).date() - timedelta(days=age_days + 1)
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)

    return [
        {
            "t": f"{day.isoformat()}T04:00:00Z",
            "o": 12.0,
            "h": 12.2,
            "l": 11.8,
            "c": 12.0,
            "v": 2_000_000,
        }
        for day in reversed(dates)
    ]


def test_sec_fallback_uses_validated_recent_closing_price(monkeypatch):
    monkeypatch.setattr(
        research_scanner,
        "get_recent_daily_bars",
        lambda symbol: make_sec_fallback_bars(),
    )
    calls = []

    def fake_estimate(symbol, price):
        calls.append((symbol, price))
        return {"estimated_market_cap": 500_000_000}

    monkeypatch.setattr(
        research_scanner, "estimate_market_cap", fake_estimate
    )

    result = research_scanner._estimate_using_sec("TEST")

    assert result["estimated_market_cap"] == 500_000_000
    assert calls == [("TEST", 12.0)]


@pytest.mark.parametrize(
    "problem,expected_error",
    [
        ("stale", "Stale Alpaca daily price"),
        ("short", "Not enough recent Alpaca daily bars"),
        ("malformed", "Invalid daily bar"),
    ],
)
def test_sec_fallback_rejects_unreliable_price_before_estimate(
    monkeypatch, problem, expected_error
):
    bars = make_sec_fallback_bars(age_days=30 if problem == "stale" else 0)
    if problem == "short":
        bars = bars[-19:]
    elif problem == "malformed":
        bars[-1]["c"] = -12.0

    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars
    )

    def should_not_estimate(symbol, price):
        pytest.fail("SEC estimate must not use unreliable Alpaca prices")

    monkeypatch.setattr(
        research_scanner, "estimate_market_cap", should_not_estimate
    )

    with pytest.raises(RuntimeError, match=expected_error):
        research_scanner._estimate_using_sec("TEST")


@pytest.mark.parametrize("problem", ["malformed_older", "duplicate_older"])
def test_sec_fallback_rejects_bad_history_outside_recent_twenty(
    monkeypatch, problem,
):
    # Both records are excluded from bars[-20:], but must still be
    # validated before an SEC market-cap estimate uses Alpaca's price.
    bars = make_sec_fallback_bars(count=21)
    if problem == "malformed_older":
        bars[0]["v"] = -1
    else:
        bars[0]["t"] = bars[1]["t"]

    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail(
            "SEC estimate must not use partially invalid history"
        ),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        research_scanner._estimate_using_sec("TEST")


@pytest.mark.parametrize("problem", ["zero_volume", "weekend"])
def test_sec_fallback_rejects_untraded_daily_prices(monkeypatch, problem):
    bars = make_sec_fallback_bars()
    if problem == "zero_volume":
        bars[-1]["v"] = 0
    else:
        latest_date = datetime.fromisoformat(
            bars[-1]["t"].replace("Z", "+00:00")
        ).date()
        saturday = latest_date + timedelta(
            days=(5 - latest_date.weekday()) % 7
        )
        bars[-1]["t"] = f"{saturday.isoformat()}T04:00:00Z"

    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail(
            "Untraded daily bar must not support SEC market-cap estimate"
        ),
    )

    with pytest.raises(RuntimeError, match="Invalid daily bar"):
        research_scanner._estimate_using_sec("TEST")


def test_sec_fallback_failure_classifies_as_unverified(monkeypatch):
    fake_fmp_failure(monkeypatch)
    bars = make_sec_fallback_bars(count=21)
    bars[0]["v"] = -1
    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail(
            "Unverified price must not reach SEC estimation"
        ),
    )
    monkeypatch.setattr(
        research_scanner, "get_stock_candidate",
        lambda symbol, market_cap: pytest.fail(
            "Unverified SEC fallback must not screen a candidate"
        ),
    )

    result = research_scanner.scan_stock("TEST")
    assert result.qualifies is False
    assert result.provisional is False
    assert result.data_unverified is True
    assert any("Invalid daily bar" in reason for reason in result.reasons)



def test_sec_fallback_rejects_discontinuous_recent_daily_sample(monkeypatch):
    bars = make_sec_fallback_bars()
    for bar in bars[:10]:
        stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        bar["t"] = (stamp - timedelta(days=14)).isoformat()
    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail(
            "SEC fallback must not estimate using a discontinuous sample"
        ),
    )
    with pytest.raises(RuntimeError, match="Discontinuous recent daily bars"):
        research_scanner._estimate_using_sec("TEST")


def test_discontinuous_sec_fallback_is_classified_unverified(monkeypatch):
    fake_fmp_failure(monkeypatch)
    bars = make_sec_fallback_bars()
    for bar in bars[:10]:
        stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
        bar["t"] = (stamp - timedelta(days=14)).isoformat()
    monkeypatch.setattr(
        research_scanner, "get_recent_daily_bars", lambda symbol: bars,
    )
    monkeypatch.setattr(
        research_scanner, "estimate_market_cap",
        lambda symbol, price: pytest.fail("Do not use discontinuous prices"),
    )
    result = research_scanner.scan_stock("TEST")
    assert result.qualifies is False
    assert result.data_unverified is True
    assert any("Discontinuous recent daily bars" in reason for reason in result.reasons)
