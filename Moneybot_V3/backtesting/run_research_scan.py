
"""Moneybot V3 read-only stock research scan."""

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


# Market capitalization is retrieved automatically from FMP.
WATCHLIST = [
    ("SOFI", None),
    ("F", None),
    ("SNAP", None),
    ("PLUG", None),
    ("LCID", None),
]


def run_scan(watchlist=None):
    """Screen stocks using FMP and Alpaca market data."""

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
    print(f"Stocks requested: {len(watchlist)}")
    print()

    results = scan_stocks(watchlist)

    print_results(results)

    passed = sum(result.qualifies for result in results)
    rejected = len(results) - passed

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"REJECTED: {rejected}")
    print("=" * 50)

    return results


if __name__ == "__main__":
    run_scan()
