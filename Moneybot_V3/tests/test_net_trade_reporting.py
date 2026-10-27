"""Regression checks for consistent V3 net-of-cost research reporting."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting import run_backtest as cli
from backtesting.trade_simulator import SimulatedTrade, net_trade_profit


def test_realized_trade_pnl_deducts_both_commissions():
    trade = SimulatedTrade(
        entry_time=None, exit_time=None,
        entry_price=100.0, exit_price=102.0,
        quantity=3, exit_reason="target",
        entry_fee=1.25, exit_fee=0.75,
    )
    assert net_trade_profit(trade) == pytest.approx(4.0)


def test_realized_trade_pnl_can_be_negative_for_gross_winner():
    trade = SimulatedTrade(
        entry_time=None, exit_time=None,
        entry_price=100.0, exit_price=100.5,
        quantity=1, exit_reason="target",
        entry_fee=0.5, exit_fee=0.5,
    )
    assert net_trade_profit(trade) == pytest.approx(-0.5)


def test_six_month_cli_trade_details_show_net_not_gross_pnl(monkeypatch, capsys):
    trade = SimulatedTrade(
        entry_time="entry", exit_time="exit",
        entry_price=100.0, exit_price=102.0,
        quantity=1, exit_reason="target",
        entry_fee=0.75, exit_fee=0.75,
    )
    report = SimpleNamespace(
        signals=[object()], trades=[trade], trade_count=1,
        winning_trades=1, losing_trades=0, win_rate_pct=100.0,
        net_profit=0.5, return_pct=0.05, ending_cash=1000.5,
        average_win=0.5, average_loss=0.0, profit_factor=0.0,
        maximum_drawdown_pct=0.0, stop_loss_exits=0,
        target_exits=1, end_of_day_exits=0,
    )
    calls = []
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(cli, "run_backtest", lambda **kwargs: (calls.append(kwargs), report)[1])
    cli.main()
    output = capsys.readouterr().out
    assert "P/L $0.50" in output
    assert "P/L $2.00" not in output
    assert "Net profit/loss: $0.50" in output
    assert "Default commission and spread are zero" in output
    assert "Hypothetical slippage: 0.10% per side" in output
    assert calls[0]["commission_per_share"] == 0.0
    assert calls[0]["spread_pct"] == 0.0
    assert calls[0]["expected_symbol"] == "SPY"
