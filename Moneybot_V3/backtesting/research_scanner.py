
"""Moneybot V3 stock research scanner.

Combines read-only market data, market capitalization,
and stock screening rules.

Research only. No brokerage orders or live trading.
"""

from dataclasses import dataclass
from math import isfinite

from backtesting.download_data import validate_symbol
from backtesting.market_cap_data import (
    MarketCapDataError,
    get_market_cap,
)
from backtesting.market_data import get_stock_candidate
from backtesting.stock_screener import screen_stock


@dataclass(frozen=True)
class ResearchResult:
    symbol: str
    qualifies: bool
    reasons: tuple


def scan_stock(symbol, market_cap=None):
    """Evaluate one stock against V3 research requirements."""

    symbol = validate_symbol(symbol)

    # Retrieve market capitalization automatically when
    # no value was provided.
    if market_cap is None:
        try:
            market_cap = get_market_cap(symbol)
        except (MarketCapDataError, RuntimeError, ValueError) as error:
            return ResearchResult(
                symbol=symbol,
                qualifies=False,
                reasons=(
                    f"Verified market capitalization is required: {error}",
                ),
            )

    # Reject invalid market-cap inputs before requesting
    # any additional market data.
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
    print("Market capitalization: FMP data provider")
    print("Read-only research. No trades submitted.")
