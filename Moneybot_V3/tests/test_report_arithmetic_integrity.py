"""Fail-closed arithmetic tests for V3 historical research reporting.

The simulator is mocked to exercise report boundary conditions that ordinary
market prices cannot reliably reproduce. No network, broker, or live orders.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting import pipeline


@pytest.fixture
def report_with_profits(monkeypatch):
    bar = SimpleNamespace(
        timestamp=datetime(2026, 10, 12, 9, 30,
                           tzinfo=ZoneInfo("America/New_York")),
        open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
    )
    monkeypatch.setattr(pipeline, "load_price_bars", lambda *a, **kw: [bar])
    monkeypatch.setattr(pipeline, "generate_breakout_signals", lambda bars: [])

    def evaluate(profits, starting_cash=1000.0):
        values = iter(profits)
        monkeypatch.setattr(
            pipeline, "simulate_trades",
            lambda *a, **kw: [SimpleNamespace(exit_reason="target") for _ in profits],
        )
        monkeypatch.setattr(
            pipeline, "net_trade_profit", lambda trade: next(values),
        )
        return pipeline.run_backtest(
            "offline-fixture.csv", starting_cash=starting_cash,
        )

    return evaluate


@pytest.mark.parametrize("invalid", [
    0, -1, True, "1000", float("nan"), float("inf"), 10 ** 400,
])
def test_report_rejects_invalid_starting_cash(report_with_profits, invalid):
    with pytest.raises(ValueError, match="Invalid starting cash"):
        report_with_profits([], invalid)


@pytest.mark.parametrize("invalid", [
    float("nan"), float("inf"), float("-inf"), True, "1", 10 ** 400,
])
def test_report_rejects_nonfinite_trade_profit(report_with_profits, invalid):
    with pytest.raises(ValueError, match="Non-finite simulated trade profit"):
        report_with_profits([invalid])


def test_report_rejects_overflowed_total_profit(report_with_profits):
    with pytest.raises(ValueError, match="Non-finite research return or equity"):
        report_with_profits([1e308, 1e308], starting_cash=1e307)


def test_report_rejects_overflowed_percentage(report_with_profits):
    with pytest.raises(ValueError, match="Non-finite research return or equity"):
        report_with_profits([1e100], starting_cash=1e-300)


def test_report_rejects_overflowed_gross_wins(report_with_profits):
    # Alternating trades keep net PnL finite, but gross wins overflow.
    with pytest.raises(ValueError, match="Non-finite research trade statistics"):
        report_with_profits(
            [1e308, -1e308, 1e308, -1e308],
            starting_cash=1e308,
        )


def test_report_rejects_overflowed_profit_factor(report_with_profits):
    with pytest.raises(ValueError, match="Non-finite research trade statistics"):
        report_with_profits([1e306, -1e-308], starting_cash=1e307)


def test_report_rejects_negative_ending_equity(report_with_profits):
    with pytest.raises(ValueError, match="Negative cash-funded research equity"):
        report_with_profits([-1100.0])


def test_report_rejects_intermediate_insolvency_even_if_recovered(report_with_profits):
    with pytest.raises(ValueError, match="Invalid simulated closed-trade equity"):
        report_with_profits([-1100.0, 1200.0])


def test_finite_research_report_still_works(report_with_profits):
    report = report_with_profits([10.0, -4.0, 2.0])
    assert report.net_profit == 8.0
    assert report.ending_cash == 1008.0
    assert report.return_pct == pytest.approx(0.8)
    assert report.trade_count == 3
    assert report.winning_trades == 2
    assert report.losing_trades == 1
    assert report.profit_factor == 3.0

@pytest.mark.parametrize("later_profit", [0.0, 10.0, 1000.0])
def test_report_rejects_trades_after_exact_account_depletion(
    report_with_profits, later_profit,
):
    with pytest.raises(ValueError, match="after cash-funded account depletion"):
        report_with_profits([-1000.0, later_profit])


def test_report_allows_exact_total_loss_as_final_trade(report_with_profits):
    report = report_with_profits([-1000.0])
    assert report.ending_cash == 0.0
    assert report.net_profit == -1000.0
    assert report.maximum_drawdown_pct == 100.0
    assert report.trade_count == 1

