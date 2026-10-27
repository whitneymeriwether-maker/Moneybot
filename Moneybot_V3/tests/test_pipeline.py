
"""Tests for the Moneybot V3 backtesting pipeline."""

import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.pipeline import (
    run_backtest, validate_regular_session_gaps,
    validate_regular_session_coverage, validate_research_window,
)

NY = ZoneInfo("America/New_York")


def write_prices(filename, breakout=True):
    """Create a small artificial historical price dataset."""
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

    assert report.average_win == 0
    assert report.average_loss == 0
    assert report.profit_factor == 0
    assert report.maximum_drawdown_pct == 0
    assert report.stop_loss_exits == 0
    assert report.target_exits == 0
    assert report.end_of_day_exits == 0


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


def test_winning_trade_diagnostics(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    report = run_backtest(filename, slippage_pct=0)

    assert report.average_win == pytest.approx(report.net_profit)
    assert report.average_loss == 0
    assert report.maximum_drawdown_pct == 0
    assert report.target_exits == 1
    assert report.stop_loss_exits == 0


def test_diagnostics_with_mixed_trades(tmp_path, monkeypatch):
    """Verify calculations using controlled simulated trades."""
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    fake_trades = [
        SimpleNamespace(
            entry_price=100,
            exit_price=110,
            quantity=1,
            exit_reason="target",
            entry_fee=0.0,
            exit_fee=0.0,
        ),
        SimpleNamespace(
            entry_price=100,
            exit_price=95,
            quantity=1,
            exit_reason="stop",
            entry_fee=0.0,
            exit_fee=0.0,
        ),
        SimpleNamespace(
            entry_price=100,
            exit_price=97,
            quantity=1,
            exit_reason="end_of_day",
            entry_fee=0.0,
            exit_fee=0.0,
        ),
    ]

    monkeypatch.setattr(
        "backtesting.pipeline.simulate_trades",
        lambda *args, **kwargs: fake_trades,
    )

    report = run_backtest(filename, slippage_pct=0)

    assert report.trade_count == 3
    assert report.winning_trades == 1
    assert report.losing_trades == 2

    assert report.net_profit == pytest.approx(2)
    assert report.ending_cash == pytest.approx(1002)
    assert report.average_win == pytest.approx(10)
    assert report.average_loss == pytest.approx(-4)
    assert report.profit_factor == pytest.approx(1.25)

    # Equity rises to 1010, then falls to 1002.
    expected_drawdown = 100 * 8 / 1010
    assert report.maximum_drawdown_pct == pytest.approx(
        expected_drawdown
    )

    assert report.stop_loss_exits == 1
    assert report.target_exits == 1
    assert report.end_of_day_exits == 1


def test_pipeline_rejects_missing_file(tmp_path):
    filename = tmp_path / "missing.csv"

    with pytest.raises(FileNotFoundError):
        run_backtest(filename)


def test_pipeline_rejects_invalid_cash(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    with pytest.raises(ValueError):
        run_backtest(filename, starting_cash=0)


def _remove_minute(filename, minute):
    with open(filename, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames
        rows = [row for row in reader if datetime.fromisoformat(row["timestamp"]).minute != minute]
    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_rejects_missing_regular_session_minute(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    _remove_minute(filename, 35)

    with pytest.raises(ValueError, match="Missing regular-session minute bars"):
        run_backtest(filename)


def test_pipeline_rejects_gap_after_breakout_signal(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    _remove_minute(filename, 46)

    with pytest.raises(ValueError, match="Missing regular-session minute bars"):
        run_backtest(filename)


def test_pipeline_gap_tolerance_is_explicit_and_does_not_invent_bars(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    _remove_minute(filename, 35)

    report = run_backtest(filename, max_regular_gap_minutes=2)
    assert report.trade_count == 0  # Opening range is still incomplete.
    assert report.signals == []


def test_regular_session_gap_check_ignores_overnight_and_weekends():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 9, 15, 59, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 9, 30, tzinfo=NY)),
    ]
    validate_regular_session_gaps(bars)


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, None, "1"])
def test_regular_session_gap_check_rejects_invalid_tolerance(invalid):
    with pytest.raises(ValueError, match="Invalid maximum regular-session gap"):
        validate_regular_session_gaps([], invalid)


def test_strict_session_coverage_rejects_truncated_close(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError, match="Incomplete regular session"):
        run_backtest(filename, require_full_regular_sessions=True)


def test_strict_session_coverage_rejects_truncated_open():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 9, 31, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 15, 59, tzinfo=NY)),
    ]
    with pytest.raises(ValueError, match="Incomplete regular session"):
        validate_regular_session_coverage(bars)


def test_strict_session_coverage_ignores_extended_hours_and_weekends():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 8, 0, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 9, 30, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 15, 59, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 17, 0, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 17, 9, 30, tzinfo=NY)),
    ]
    validate_regular_session_coverage(bars)


def test_strict_session_coverage_rejects_no_regular_bars():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 17, 9, 30, tzinfo=NY))
    ]
    with pytest.raises(ValueError, match="No regular-session minute bars"):
        validate_regular_session_coverage(bars)


def test_strict_session_coverage_accepts_complete_minute_history(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with filename.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames
        rows = list(reader)
    start = datetime(2026, 10, 12, 9, 30, tzinfo=NY)
    for minute in range(18, 390):
        rows.append({
            "timestamp": (start + timedelta(minutes=minute)).isoformat(),
            "open": 100, "high": 101, "low": 99,
            "close": 100, "volume": 1000,
        })
    with filename.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = run_backtest(
        filename, slippage_pct=0, require_full_regular_sessions=True
    )
    assert report.trade_count == 1


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", [], float("nan")])
def test_strict_session_requirement_rejects_invalid_option(tmp_path, invalid):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError, match="Invalid full regular-session requirement"):
        run_backtest(filename, require_full_regular_sessions=invalid)


def test_research_window_accepts_expected_endpoint_session(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    report = run_backtest(
        filename,
        expected_session_span=(date(2026, 10, 12), date(2026, 10, 12)),
    )
    assert report.trade_count == 1


def test_research_window_rejects_truncated_date_span(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError, match="expected session endpoints"):
        run_backtest(
            filename,
            expected_session_span=(date(2026, 10, 12), date(2026, 10, 13)),
        )


def test_research_window_rejects_too_few_observed_sessions(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError, match="Insufficient observed sessions"):
        run_backtest(
            filename,
            expected_session_span=(date(2026, 10, 12), date(2026, 10, 12)),
            minimum_observed_sessions=2,
        )


def test_research_window_counts_distinct_new_york_dates():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 13, 30, tzinfo=ZoneInfo("UTC"))),
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 14, 30, tzinfo=ZoneInfo("UTC"))),
        SimpleNamespace(timestamp=datetime(2026, 10, 13, 13, 30, tzinfo=ZoneInfo("UTC"))),
    ]
    validate_research_window(
        bars, date(2026, 10, 12), date(2026, 10, 13),
        minimum_observed_sessions=2,
    )
    with pytest.raises(ValueError, match="Insufficient observed sessions"):
        validate_research_window(
            bars, date(2026, 10, 12), date(2026, 10, 13),
            minimum_observed_sessions=3,
        )


def test_research_window_ignores_only_extended_hours_and_weekend():
    bars = [
        SimpleNamespace(timestamp=datetime(2026, 10, 12, 8, 0, tzinfo=NY)),
        SimpleNamespace(timestamp=datetime(2026, 10, 17, 9, 30, tzinfo=NY)),
    ]
    with pytest.raises(ValueError, match="No regular-session bars"):
        validate_research_window(
            bars, date(2026, 10, 12), date(2026, 10, 12),
        )


@pytest.mark.parametrize("first,last", [
    (datetime(2026, 10, 12), date(2026, 10, 12)),
    (date(2026, 10, 12), "2026-10-12"),
    (date(2026, 10, 13), date(2026, 10, 12)),
])
def test_research_window_rejects_invalid_session_dates(first, last):
    with pytest.raises(ValueError, match="Invalid expected research session window"):
        validate_research_window([], first, last)


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, None, "120"])
def test_research_window_rejects_invalid_minimum(invalid):
    with pytest.raises(ValueError, match="Invalid minimum observed sessions"):
        validate_research_window(
            [], date(2026, 10, 12), date(2026, 10, 12), invalid,
        )


def test_pipeline_rejects_minimum_without_expected_span(tmp_path):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError, match="requires a session span"):
        run_backtest(filename, minimum_observed_sessions=120)



def test_pipeline_net_returns_include_commissions_and_spread(tmp_path):
    """A cost-bearing simulation must reconcile with its own fill accounting."""
    filename = tmp_path / "prices.csv"
    write_prices(filename)

    gross = run_backtest(filename, slippage_pct=0)
    costly = run_backtest(
        filename, slippage_pct=0,
        commission_per_share=0.25, spread_pct=0.002,
    )
    assert gross.trade_count == costly.trade_count == 1
    expected_net = sum(
        (trade.exit_price - trade.entry_price) * trade.quantity
        - trade.entry_fee - trade.exit_fee
        for trade in costly.trades
    )
    assert costly.net_profit == pytest.approx(expected_net)
    assert costly.net_profit < gross.net_profit
    assert costly.ending_cash == pytest.approx(costly.starting_cash + expected_net)
    assert costly.return_pct == pytest.approx(100 * expected_net / costly.starting_cash)
    assert costly.average_win == pytest.approx(expected_net)


def test_pipeline_fees_can_turn_gross_winner_into_net_loser(tmp_path, monkeypatch):
    """Win rate and drawdown must use net PnL, not raw price changes."""
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    trade = SimpleNamespace(
        entry_price=100.0, exit_price=100.50, quantity=1,
        entry_fee=0.50, exit_fee=0.50, exit_reason="target",
    )
    monkeypatch.setattr(
        "backtesting.pipeline.simulate_trades",
        lambda *args, **kwargs: [trade],
    )
    report = run_backtest(filename, slippage_pct=0)
    assert report.net_profit == pytest.approx(-0.50)
    assert report.ending_cash == pytest.approx(999.50)
    assert report.winning_trades == 0
    assert report.losing_trades == 1
    assert report.win_rate_pct == 0
    assert report.average_loss == pytest.approx(-0.50)
    assert report.maximum_drawdown_pct == pytest.approx(0.05)


@pytest.mark.parametrize("option,value", [
    ("commission_per_share", -0.01),
    ("commission_per_share", True),
    ("spread_pct", 1.0),
    ("spread_pct", "0.001"),
    ("max_participation", 0),
    ("max_participation", True),
])
def test_pipeline_rejects_invalid_cost_and_liquidity_options(tmp_path, option, value):
    filename = tmp_path / "prices.csv"
    write_prices(filename)
    with pytest.raises(ValueError):
        run_backtest(filename, **{option: value})
