
"""Moneybot V3 read-only stock research scan.

Reports verified passes, provisional candidates,
unverified market data, and rejected stocks.

No brokerage orders or live trading.
"""

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting.research_scanner import (
    print_results,
    scan_stocks,
)


# Preliminary research candidates.
# Market caps are retrieved from FMP or estimated
# provisionally using SEC shares and Alpaca prices.
WATCHLIST = [
    ("SOFI", None),
    ("F", None),
    ("SNAP", None),
    ("PLUG", None),
    ("LCID", None),
    ("OPEN", None),
    ("RIG", None),
    ("NOK", None),
    ("BB", None),
    ("ACHR", None),
    ("JOBY", None),
    ("SOUN", None),
    ("BBAI", None),
    ("CLSK", None),
    ("HIMS", None),
    ("WULF", None),
    ("MARA", None),
    ("RIOT", None),
    ("CHPT", None),
    ("DNA", None),
]


def run_scan(watchlist=None):
    """Run a read-only research scan."""

    if watchlist is None:
        watchlist = WATCHLIST

    print("=" * 50)
    print("MONEYBOT V3 STOCK RESEARCH")
    print("=" * 50)
    print("Research only. No orders submitted.")
    print("Price range: $2 to $30")
    print("Minimum average daily volume: 1,000,000 shares")
    print("Market capitalization: $300M to $10B")
    print("Maximum bid-ask spread: 0.15%")
    print("IEX volume is partial-market data.")
    print("SEC market-cap estimates are provisional.")
    print(f"Stocks requested: {len(watchlist)}")
    print()

    results = scan_stocks(watchlist)

    print_results(results)

    passed = sum(
        result.qualifies
        for result in results
    )

    provisional = sum(
        result.provisional and not result.qualifies
        for result in results
    )

    data_unverified = sum(
        result.data_unverified
        for result in results
    )

    rejected = (
        len(results)
        - passed
        - provisional
        - data_unverified
    )

    print()
    print("=" * 50)
    print(f"Passed: {passed}")
    print(f"Provisional: {provisional}")
    print(f"Data unverified: {data_unverified}")
    print(f"Rejected: {rejected}")
    print("=" * 50)

    return results


if __name__ == "__main__":
    run_scan()
