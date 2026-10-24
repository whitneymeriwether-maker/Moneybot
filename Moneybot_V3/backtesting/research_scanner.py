
"""Moneybot V3 stock research scanner.

Combines read-only market data, market capitalization,
and stock screening rules.

SEC estimates are diagnostic only and cannot qualify
a stock for the verified research universe.

No brokerage orders or live trading.
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


def _estimate_using_sec(symbol):
    """Try SEC share data with Alpaca's recent closing price."""

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


def scan_stock(symbol, market_cap=None):
    """Evaluate one stock against V3 research requirements."""

    symbol = validate_symbol(symbol)

    if market_cap is None:
        try:
            market_cap = get_market_cap(symbol)

        except (MarketCapDataError, RuntimeError, ValueError) as fmp_error:
            try:
                estimate = _estimate_using_sec(symbol)

                return ResearchResult(
                    symbol=symbol,
                    qualifies=False,
                    reasons=(
                        "ESTIMATE ONLY - not approved by verified screener",
                        (
                            "SEC/Alpaca estimated market cap: "
                            f"${estimate['estimated_market_cap']:,.0f}"
                        ),
                        (
                            "SEC shares observation date: "
                            f"{estimate['observation_date']}"
                        ),
                        (
                            "SEC shares filing date: "
                            f"{estimate['filed_date']}"
                        ),
                        f"FMP unavailable: {fmp_error}",
                    ),
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
            reasons=("Invalid market capitalization",),
        )

    try:
        candidate = get_stock_candidate(
            symbol=symbol,
            market_cap=market_cap,
        )

        screening = screen_stock(candidate)

        return ResearchResult(
            symbol=symbol,
            qualifies=screening.qualifies,
            reasons=screening.reasons,
        )

    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return ResearchResult(
            symbol=symbol,
            qualifies=False,
            reasons=(f"Market data unavailable: {error}",),
        )


def scan_stocks(stock_list):
    """Evaluate multiple (symbol, market_cap) pairs."""

    results = []

    for symbol, market_cap in stock_list:
        results.append(
            scan_stock(
                symbol=symbol,
                market_cap=market_cap,
            )
        )

    return results


def print_results(results):
    """Display research results in a readable format."""

    for result in results:
        status = "PASS" if result.qualifies else "REJECT"

        print(f"{result.symbol}: {status}")

        for reason in result.reasons:
            print(f"  - {reason}")


if __name__ == "__main__":
    print("Moneybot V3 Research Scanner")
    print("Research universe: $2-$30 stocks")
    print("Market capitalization: FMP verified data")
    print("SEC/Alpaca fallback: estimate only")
    print("Read-only research. No trades submitted.")
