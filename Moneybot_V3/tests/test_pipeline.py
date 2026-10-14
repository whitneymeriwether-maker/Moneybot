
"""Tests for the Moneybot V3 backtesting pipeline."""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.pipeline import run_backtest

NY = ZoneInfo("America/New_York")


def write_prices(filename, breakout=True):
    """Create a small, artificial historical price dataset."""
    start = datetime(2026, 10, 12, 9, 30, tzinfo=NY)
    rows = []

    for minute in range(15):
        rows.append({
            "timestamp": (start + timedelta(minutes=minute)).isoformat(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        })

    rows.append({
        "timestamp": (start + timedelta(minutes=15)).isoformat(),
        "open": 102 if breakout else 100,
        "high": 102.5 if breakout else 100.5,
        "low": 101.5 if breakout else 99.5,
        "close": 102 if breakout else 100,
        "volume": 1000,
    })

    if breakout:
        rows.append({
            "timestamp": (start + timedelta(minutes=16)).isoformat(),
            "open": 102,
            "high": 102.5,
            "low": 101.5,
            "close": 102,
            "volume": 1000,
        })
        rows.append({
            "timestamp": (start + timedelta(minutes=17)).isoformat(),
            "open": 103,
            "high": 108,
            "low": 102,
            "close": 107,
            "volume": 1000,
        })

    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "timestamp", "open", "high",
                "low", "close", "volume"
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_detects_and_simulates_breakout(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    report = run_backtest(filename, slippage_pct=0)

    assert len(report.signals) == 1
    assert report.trade_count == 1
    assert report.winning_trades == 1
    assert report.losing_trades == 0
    assert report.net_profit > 0
    assert report.ending_cash > 1000
    assert report.win_rate_pct == 100


def test_pipeline_without_breakout(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename, breakout=False)

    report = run_backtest(filename)

    assert len(report.signals) == 0
    assert report.trade_count == 0
    assert report.net_profit == 0
    assert report.ending_cash == 1000
    assert report.win_rate_pct == 0


def test_report_profit_matches_trades(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    report = run_backtest(filename, slippage_pct=0)

    calculated_profit = sum(
        (trade.exit_price - trade.entry_price) * trade.quantity
        for trade in report.trades
    )

    assert report.net_profit == pytest.approx(calculated_profit)
    assert report.return_pct == pytest.approx(
        100 * report.net_profit / report.starting_cash
    )


def test_pipeline_rejects_missing_file(tmp_path):
    filename = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError):
        run_backtest(filename)


def test_pipeline_rejects_invalid_cash(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    with pytest.raises(ValueError):
        run_backtest(filename, starting_cash=0)
