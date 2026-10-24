
"""Moneybot V3 stock research scanner.

Uses FMP market capitalization when available.
Uses SEC shares outstanding and Alpaca prices as a
provisional research fallback.

Separates verified passes, provisional candidates,
unverified data, and confirmed screening failures.

Research only. No brokerage orders or live trading.
"""

from dataclasses import dataclass
from math import isfinite

from backtesting.download_data import validate_symbol
from backtesting.market_cap_data import (
    MarketCapDataError,
    get_market_cap,
)
from backtesting.market_data import (
    get_recent_daily_bars,
    get_stock_candidate,
)
from backtesting.sec_market_cap import (
    SECMarketCapError,
    estimate_market_cap,
)
from backtesting.stock_screener import screen_stock


@dataclass(frozen=True)
class ResearchResult:
    symbol: str
    qualifies: bool
    reasons: tuple
    provisional: bool = False
    data_unverified: bool = False


def _estimate_using_sec(symbol):
    """Estimate market cap using SEC shares and Alpaca price."""

    bars = get_recent_daily_bars(symbol)

    if not bars:
        raise RuntimeError(
            f"No recent Alpaca daily prices for {symbol}"
        )

    price = float(bars[-1]["c"])

    if not isfinite(price) or price <= 0:
        raise ValueError(
            f"Invalid Alpaca closing price for {symbol}"
        )

    return estimate_market_cap(symbol, price)


def _estimate_details(market_cap, estimate):
    """Describe the limitations of an SEC market-cap estimate."""

    return (
        "Market cap is an SEC/Alpaca estimate, not verified",
        f"Estimated market cap: ${market_cap:,.0f}",
        (
            "SEC shares observation date: "
            f"{estimate['observation_date']}"
        ),
        (
            "SEC shares filing date: "
            f"{estimate['filed_date']}"
        ),
    )


def scan_stock(symbol, market_cap=None):
    """Classify a stock using available research data."""

    symbol = validate_symbol(symbol)
    estimated = False
    estimate_details = ()

    if market_cap is None:
        try:
            market_cap = get_market_cap(symbol)

        except (MarketCapDataError, RuntimeError, ValueError) as fmp_error:
            try:
                estimate = _estimate_using_sec(symbol)
                market_cap = estimate["estimated_market_cap"]
                estimated = True
                estimate_details = _estimate_details(
                    market_cap,
                    estimate,
                )

            except (
                SECMarketCapError,
                RuntimeError,
                ValueError,
                KeyError,
                TypeError,
            ) as sec_error:
                return ResearchResult(
                    symbol=symbol,
                    qualifies=False,
                    data_unverified=True,
                    reasons=(
                        f"FMP unavailable: {fmp_error}",
                        f"SEC estimate unavailable: {sec_error}",
                    ),
                )

    if (
        isinstance(market_cap, bool)
        or not isinstance(market_cap, (int, float))
        or not isfinite(market_cap)
        or market_cap <= 0
    ):
        return ResearchResult(
            symbol=symbol,
            qualifies=False,
            data_unverified=True,
            reasons=("Invalid market capitalization",),
        )

    try:
        candidate = get_stock_candidate(
            symbol=symbol,
            market_cap=market_cap,
        )

        screening = screen_stock(candidate)
        reasons = tuple(screening.reasons)

        # IEX-only volume and spread are not consolidated market
        # measurements. Low IEX volume and a wide IEX spread
        # cannot establish a failure of the market-wide rules.
        low_iex_volume = (
            candidate.average_daily_volume < 1_000_000
        )
        wide_iex_spread = "Bid-ask spread too wide" in reasons

        inconclusive_reasons = {
            "Insufficient average daily volume",
            "Bid-ask spread too wide",
        }
        reasons = tuple(
            reason for reason in reasons
            if reason not in inconclusive_reasons
        )

        # Confirmed failures take precedence over inconclusive
        # IEX observations. Never promote uncertain data to PASS.
        if reasons:
            return ResearchResult(
                symbol=symbol,
                qualifies=False,
                reasons=reasons + estimate_details,
            )

        if low_iex_volume or wide_iex_spread:
            unverified = []
            if low_iex_volume:
                unverified.append(
                    "IEX-only volume below 1,000,000 shares; "
                    "consolidated volume not verified"
                )
            if wide_iex_spread:
                unverified.append(
                    "IEX-only bid-ask spread exceeds 0.15%; "
                    "consolidated NBBO spread not verified"
                )

            return ResearchResult(
                symbol=symbol,
                qualifies=False,
                data_unverified=True,
                reasons=tuple(unverified) + estimate_details,
            )

        if estimated:
            return ResearchResult(
                symbol=symbol,
                qualifies=False,
                provisional=True,
                reasons=estimate_details,
            )

        return ResearchResult(
            symbol=symbol,
            qualifies=screening.qualifies,
            reasons=screening.reasons,
        )

    except (
        RuntimeError,
        ValueError,
        KeyError,
        TypeError,
        OverflowError,
    ) as error:
        return ResearchResult(
            symbol=symbol,
            qualifies=False,
            data_unverified=True,
            reasons=(
                f"Market data unavailable: {error}",
            ) + estimate_details,
        )


def scan_stocks(stock_list):
    """Evaluate multiple (symbol, market_cap) pairs."""

    return [
        scan_stock(symbol=symbol, market_cap=market_cap)
        for symbol, market_cap in stock_list
    ]


def print_results(results):
    """Display research classifications."""

    for result in results:
        if result.data_unverified:
            status = "DATA UNVERIFIED"
        elif result.qualifies:
            status = "PASS"
        elif result.provisional:
            status = "PROVISIONAL"
        else:
            status = "REJECT"

        print(f"{result.symbol}: {status}")

        for reason in result.reasons:
            print(f"  - {reason}")


if __name__ == "__main__":
    print("Moneybot V3 Research Scanner")
    print("Research universe: $2-$30 stocks")
    print("FMP: market-cap provider")
    print("SEC/Alpaca: provisional estimates only")
    print("IEX volume: partial-market data")
    print("No brokerage orders submitted.")
