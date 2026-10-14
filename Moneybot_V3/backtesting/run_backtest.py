
"""Run Moneybot V3's six-month historical SPY backtest.

Research only. No brokerage connections or real orders.
"""

import sys
from pathlib import Path

V3_FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V3_FOLDER))

from backtesting.pipeline import run_backtest


def main():
    data_file = (
        V3_FOLDER
        / "data"
        / "SPY_1min_2026_04_to_09.csv"
    )

    if not data_file.is_file():
        raise FileNotFoundError(
            f"Historical SPY data file not found: {data_file}"
        )

    print("=" * 45)
    print("MONEYBOT V3 - SIX-MONTH BACKTEST")
    print("=" * 45)
    print("Symbol: SPY")
    print("Period: April 1 - September 30, 2026")
    print("Starting virtual balance: $1,000.00")
    print()

    report = run_backtest(
        csv_filename=data_file,
        starting_cash=1000.0,
        risk_per_trade=0.015,
        slippage_pct=0.001,
    )

    print(f"Breakout signals: {len(report.signals)}")
    print(f"Completed trades: {report.trade_count}")
    print(f"Winning trades: {report.winning_trades}")
    print(f"Losing trades: {report.losing_trades}")
    print(f"Win rate: {report.win_rate_pct:.2f}%")
    print()

    print(f"Net profit/loss: ${report.net_profit:,.2f}")
    print(f"Total return: {report.return_pct:.2f}%")
    print(f"Ending virtual balance: ${report.ending_cash:,.2f}")
    print()

    print("TRADE DETAILS")
    print("-" * 45)

    if not report.trades:
        print("No completed trades.")

    for number, trade in enumerate(report.trades, start=1):
        profit = (
            trade.exit_price - trade.entry_price
        ) * trade.quantity

        print(
            f"{number}. {trade.entry_time} | "
            f"{trade.quantity} shares | "
            f"Entry ${trade.entry_price:.2f} | "
            f"Exit ${trade.exit_price:.2f} | "
            f"P/L ${profit:.2f} | "
            f"{trade.exit_reason}"
        )

    print()
    print("Research simulation only.")
    print("Results exclude commissions and some market costs.")
    print("Historical IEX data may omit market activity.")


if __name__ == "__main__":
    main()
