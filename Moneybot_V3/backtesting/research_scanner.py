
"""Moneybot V3 stock research scanner.

Uses FMP market capitalization when available.
Uses SEC shares outstanding and Alpaca prices as a
provisional research fallback.

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


def scan_stock(symbol, market_cap=None):
    """Evaluate a stock using verified or provisional data."""

    symbol = validate_symbol(symbol)
    estimated = False
    estimate_details = None

    if market_cap is None:
        try:
            market_cap = get_market_cap(symbol)

        except (MarketCapDataError, RuntimeError, ValueError) as fmp_error:
            try:
                estimate_details = _estimate_using_sec(symbol)
                market_cap = estimate_details["estimated_market_cap"]
                estimated = True

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

        if estimated:
            details = (
                "Market cap is an SEC/Alpaca estimate, not verified",
                f"Estimated market cap: ${market_cap:,.0f}",
                (
                    "SEC shares observation date: "
                    f"{estimate_details['observation_date']}"
                ),
                (
                    "SEC shares filing date: "
                    f"{estimate_details['filed_date']}"
                ),
            )

            if screening.qualifies:
                return ResearchResult(
                    symbol=symbol,
                    qualifies=False,
                    provisional=True,
                    reasons=details,
                )

            return ResearchResult(
                symbol=symbol,
                qualifies=False,
                reasons=screening.reasons + details,
            )

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

    return [
        scan_stock(symbol=symbol, market_cap=market_cap)
        for symbol, market_cap in stock_list
    ]


def print_results(results):
    """Display verified, provisional, and rejected stocks."""

    for result in results:
        if result.qualifies:
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
    print("FMP: verified market-cap provider")
    print("SEC/Alpaca: provisional estimates only")
    print("No brokerage orders submitted.")
