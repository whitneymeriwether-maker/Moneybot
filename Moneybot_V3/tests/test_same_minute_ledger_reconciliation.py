"""Regression tests for same-minute simulated fills and audited replay.

These test only deterministic hypothetical OHLC outcomes, not executable fills.
"""

import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backtesting.ledger_reconciliation import reconcile_closed_simulation
from backtesting.pipeline import run_backtest
from backtesting.trade_simulator import SimulatedTrade


T = datetime(2026, 10, 12, 13, 46, tzinfo=timezone.utc)


def _trade(*, entry_at=T, exit_at=T, entry=100.0, exit=99.0):
    return SimulatedTrade(
        entry_time=entry_at, exit_time=exit_at,
        entry_price=entry, exit_price=exit, quantity=2,
        exit_reason="stop", entry_fee=0.0, exit_fee=0.0,
    )


def test_same_minute_stop_reconciles_to_audited_paper_fills():
    report = reconcile_closed_simulation([_trade()], symbol="SPY")
    assert report == {
        "trade_count": 1, "audited_fills": 2,
        "starting_cash": "1000.00", "ending_cash": "998.00",
        "net_pnl": "-2.00",
    }


def test_sequential_same_timestamp_buy_sell_pairs_keep_fill_order():
    # The ledger's audit uses insertion order for equal timestamps.
    trades = [_trade(), _trade(entry=50, exit=55)]
    report = reconcile_closed_simulation(trades, symbol="SPY")
    assert report["audited_fills"] == 4
    assert report["ending_cash"] == "1008.00"
    assert report["net_pnl"] == "8.00"


def test_exit_before_entry_remains_invalid():
    with pytest.raises(ValueError, match="exit cannot precede entry"):
        reconcile_closed_simulation(
            [replace(_trade(), exit_time=T - timedelta(microseconds=1))],
            symbol="SPY",
        )


def test_overlapping_trades_remain_invalid_with_same_minute_support():
    first = _trade(exit_at=T + timedelta(minutes=1))
    second = _trade(entry_at=T + timedelta(seconds=30),
                    exit_at=T + timedelta(minutes=2))
    with pytest.raises(ValueError, match="overlap"):
        reconcile_closed_simulation([first, second], symbol="SPY")


def test_real_pipeline_same_minute_stop_supports_opt_in_ledger_audit(tmp_path):
    filename = tmp_path / "same_minute_stop.csv"
    ny = ZoneInfo("America/New_York")
    start = datetime(2026, 10, 12, 9, 30, tzinfo=ny)
    rows = []
    for minute in range(17):
        opening, high, low, close = (100, 101, 99, 100)
        if minute == 15:
            opening, high, low, close = (102, 102.5, 101.5, 102)
        elif minute == 16:
            # At 9:46 the hypothetical BUY is at the open (102), and the
            # bar touches the planned 100 stop later in that same minute.
            opening, high, low, close = (102, 102.5, 99, 100)
        rows.append({
            "timestamp": (start + timedelta(minutes=minute)).isoformat(),
            "open": opening, "high": high, "low": low,
            "close": close, "volume": 1000, "symbol": "SPY",
        })
    with filename.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    report = run_backtest(
        filename, expected_symbol="SPY", slippage_pct=0,
        audit_paper_ledger=True,
    )
    assert report.trade_count == 1
    assert report.trades[0].entry_time == report.trades[0].exit_time
    assert report.trades[0].exit_reason == "stop"
    assert report.net_profit == pytest.approx(-8.0)
    assert report.paper_ledger_audit["audited_fills"] == 2
    assert report.paper_ledger_audit["ending_cash"] == "992.00"
