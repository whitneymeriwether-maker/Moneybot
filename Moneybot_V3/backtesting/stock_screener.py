
"""Moneybot V3 stock screening rules.

Research only. No brokerage orders or live trading.
"""

from dataclasses import dataclass
from math import isfinite

from backtesting.download_data import validate_symbol


def _finite_number(value):
    """Fail closed on booleans, malformed numbers, and oversized integers."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, ValueError):
        return False


MIN_PRICE = 2.00
MAX_PRICE = 30.00

MIN_AVERAGE_DAILY_VOLUME = 1_000_000
MIN_MARKET_CAP = 300_000_000
MAX_MARKET_CAP = 10_000_000_000

MAX_SPREAD_PCT = 0.15


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    price: float
    average_daily_volume: float
    market_cap: float
    bid: float
    ask: float


@dataclass(frozen=True)
class ScreeningResult:
    symbol: str
    qualifies: bool
    reasons: tuple


def screen_stock(candidate):
    """Check whether a stock meets V3 research criteria."""

    reasons = []

    # The direct screener is a public research entry point. Do not let a
    # malformed or Unicode lookalike ticker pass simply because its prices
    # satisfy the numeric thresholds. Reuse the provider-side ASCII rules.
    symbol = candidate.symbol
    if type(symbol) is not str or not symbol.strip():
        reasons.append("Missing stock symbol")
    else:
        try:
            symbol = validate_symbol(symbol)
        except ValueError:
            reasons.append("Invalid stock symbol")

    numeric_values = (
        candidate.price,
        candidate.average_daily_volume,
        candidate.market_cap,
        candidate.bid,
        candidate.ask,
    )

    if not all(_finite_number(value) for value in numeric_values):
        return ScreeningResult(
            symbol=symbol,
            qualifies=False,
            reasons=("Invalid numeric market data",),
        )

    if not MIN_PRICE <= candidate.price <= MAX_PRICE:
        reasons.append("Price outside $2-$30 range")

    if candidate.average_daily_volume < MIN_AVERAGE_DAILY_VOLUME:
        reasons.append("Insufficient average daily volume")

    if not MIN_MARKET_CAP <= candidate.market_cap <= MAX_MARKET_CAP:
        reasons.append("Market cap outside research range")

    if candidate.bid <= 0 or candidate.ask <= 0:
        reasons.append("Invalid bid or ask")

    elif candidate.ask < candidate.bid:
        reasons.append("Ask price below bid price")

    elif candidate.ask == candidate.bid:
        reasons.append("Locked bid-ask quote")

    else:
        # Finite inputs can overflow when combined. Never interpret an
        # infinite midpoint as a zero-percent spread and approve the stock.
        midpoint = (candidate.bid + candidate.ask) / 2
        if not isfinite(midpoint) or midpoint <= 0:
            reasons.append("Invalid numeric market data")
        else:
            spread_pct = (
                100 * (candidate.ask - candidate.bid) / midpoint
            )
            if not isfinite(spread_pct):
                reasons.append("Invalid numeric market data")
            elif spread_pct > MAX_SPREAD_PCT:
                reasons.append("Bid-ask spread too wide")

    return ScreeningResult(
        symbol=symbol,
        qualifies=len(reasons) == 0,
        reasons=tuple(reasons),
    )


def screen_stocks(candidates):
    """Return screening results for a collection of stocks."""
    return [
        screen_stock(candidate)
        for candidate in candidates
    ]


if __name__ == "__main__":
    print("Moneybot V3 Stock Screener")
    print("Research price range: $2-$30")
    print("Minimum average daily volume: 1,000,000 shares")
    print("Maximum bid-ask spread: 0.15%")
    print("No brokerage connection or trading enabled.")
