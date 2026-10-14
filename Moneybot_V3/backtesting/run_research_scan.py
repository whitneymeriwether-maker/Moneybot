
"""Run a small, read-only Moneybot V3 stock research scan.

Market capitalization must be independently verified.
No orders or live trading.
"""

import os
import sys
from pathlib import Path

# Allow direct execution from the Moneybot_V3 directory.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from backtesting.research_scanner import (
    print_results,
    scan_stocks,
)


# Initial research watchlist.
# None means market capitalization has NOT been verified.
#
# Do not replace None with guesses. A verified market-cap
# data source will be connected in a later step.
WATCHLIST = [
    ("SOFI", None),
    ("F", None),
    ("SNAP", None),
    ("PLUG", None),
    ("LCID", None),
]


def run_scan(watchlist=None):
    """Run a research scan and return the results."""

    if watchlist is None:
        watchlist = WATCHLIST

    print("Moneybot V3 Research Scan")
    print("-------------------------")
    print(f"Stocks requested: {len(watchlist)}")
    print("Research only. No orders submitted.")
    print()

    results = scan_stocks(watchlist)

    print_results(results)

    passed = sum(result.qualifies for result in results)

    print()
    print(f"Passed: {passed}")
    print(f"Rejected: {len(results) - passed}")

    return results


if __name__ == "__main__":
    run_scan()
