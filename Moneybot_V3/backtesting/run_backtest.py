
"""Run Moneybot V3's six-month historical SPY backtest.

Research only. No brokerage connections or real orders.
"""

import sys
from datetime import date
from pathlib import Path

V3_FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V3_FOLDER))

from backtesting.pipeline import run_backtest
from backtesting.trade_simulator import net_trade_profit


# Official NYSE 2026 equity-market closures within this research window:
# https://www.nyse.com/trade/hours-calendars (checked October 26, 2026).
# No scheduled early closes occur in this April-September span.
NYSE_2026_APR_SEP_CLOSED_SESSIONS = frozenset({
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
})


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

    print("=" * 50)
    print("MONEYBOT V3 - SIX-MONTH BACKTEST")
    print("=" * 50)
    print("Symbol: SPY")
    print("Period: April 1 - September 30, 2026")
    print("Starting virtual balance: $1,000.00")
    print("Hypothetical slippage: 0.10% per side")
    print("Hypothetical commission: $0.00 per share per side")
    print("Assumed full bid-ask spread: 0.00%")
    print()

    report = run_backtest(
        csv_filename=data_file,
        starting_cash=1000.0,
        risk_per_trade=0.015,
        slippage_pct=0.001,
        commission_per_share=0.0,
        spread_pct=0.0,
        require_full_regular_sessions=True,
        require_traded_regular_minutes=True,
        expected_session_span=(date(2026, 4, 1), date(2026, 9, 30)),
        minimum_observed_sessions=120,
        closed_sessions=NYSE_2026_APR_SEP_CLOSED_SESSIONS,
        expected_symbol="SPY",
    )

    print("OVERALL PERFORMANCE")
    print("-" * 50)
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

    print("PERFORMANCE DIAGNOSTICS")
    print("-" * 50)
    print(f"Average winning trade: ${report.average_win:,.2f}")
    print(f"Average losing trade: ${report.average_loss:,.2f}")
    print(f"Profit factor: {report.profit_factor:.3f}")
    print(
        f"Maximum closed-trade drawdown: "
        f"{report.maximum_drawdown_pct:.2f}%"
    )
    print()

    print("EXIT REASONS")
    print("-" * 50)
    print(f"Stop-loss exits: {report.stop_loss_exits}")
    print(f"Profit-target exits: {report.target_exits}")
    print(f"Session/end-of-data exits: {report.end_of_day_exits}")
    print()

    print("TRADE DETAILS")
    print("-" * 50)

    if not report.trades:
        print("No completed trades.")

    for number, trade in enumerate(report.trades, start=1):
        profit = net_trade_profit(trade)

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
    print("Trade P/L is net of configured hypothetical commissions and spread.")
    print("Default commission and spread are zero; actual execution costs are unverified.")
    print("Historical IEX data may omit market activity.")
    print(
        "Drawdown is calculated from closed trades, "
        "not intratrade equity."
    )


if __name__ == "__main__":
    main()
