"""Offline simulator-to-ledger reconciliation regression tests."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from backtesting.ledger_reconciliation import reconcile_closed_simulation
from backtesting.trade_simulator import SimulatedTrade


T = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)


def trade(*, start=T, entry=100.0, exit=110.0, qty=2, entry_fee=1.0, exit_fee=0.5):
    return SimulatedTrade(
        entry_time=start, exit_time=start + timedelta(minutes=1),
        entry_price=entry, exit_price=exit, quantity=qty,
        exit_reason="target", entry_fee=entry_fee, exit_fee=exit_fee,
    )


def test_exact_cent_trades_reconcile_to_audited_disposable_ledger():
    first = trade()
    second = trade(start=T + timedelta(minutes=2), entry=50, exit=45,
                   qty=1, entry_fee=0.25, exit_fee=0.25)
    report = reconcile_closed_simulation([first, second], symbol="SPY")
    assert report == {
        "trade_count": 2, "audited_fills": 4,
        "starting_cash": "1000.00", "ending_cash": "1013.00",
        "net_pnl": "13.00",
    }


def test_empty_replay_keeps_capital_and_has_zero_audited_fills():
    assert reconcile_closed_simulation([], symbol="SPY") == {
        "trade_count": 0, "audited_fills": 0,
        "starting_cash": "1000.00", "ending_cash": "1000.00",
        "net_pnl": "0.00",
    }


def test_exact_total_loss_is_reportable():
    loss = trade(entry=1000, exit=1, qty=1, entry_fee=0, exit_fee=1)
    report = reconcile_closed_simulation([loss], symbol="SPY")
    assert report["ending_cash"] == "0.00"
    assert report["net_pnl"] == "-1000.00"


def test_negative_net_sale_proceeds_fail_closed():
    with pytest.raises(ValueError, match="Invalid paper sale proceeds"):
        reconcile_closed_simulation(
            [trade(entry=100, exit=1, qty=1, entry_fee=0, exit_fee=2)],
            symbol="SPY",
        )


@pytest.mark.parametrize("field,value", [
    ("entry_price", 100.001), ("exit_price", 110.005),
    ("entry_fee", 0.001), ("exit_fee", 0.005),
    ("entry_price", float("nan")), ("exit_price", float("inf")),
    ("quantity", True), ("quantity", 0),
    ("entry_time", T.replace(tzinfo=None)),
    ("exit_time", T - timedelta(microseconds=1)),
])
def test_invalid_or_unrepresentable_simulator_fill_fails_closed(field, value):
    with pytest.raises(ValueError):
        reconcile_closed_simulation(
            [replace(trade(), **{field: value})], symbol="SPY"
        )


def test_overlap_and_out_of_order_rejected_before_replay():
    first = trade()
    overlap = trade(start=T + timedelta(seconds=30))
    with pytest.raises(ValueError, match="overlap"):
        reconcile_closed_simulation([first, overlap], symbol="SPY")
    with pytest.raises(ValueError, match="overlap"):
        reconcile_closed_simulation([trade(start=T + timedelta(minutes=5)), first],
                                    symbol="SPY")


def test_cash_only_replay_rejects_overspending():
    with pytest.raises(ValueError, match="Insufficient hypothetical paper cash"):
        reconcile_closed_simulation([trade(entry=600, qty=2)], symbol="SPY")


def test_no_silent_rounding_of_starting_cash_or_bad_symbol():
    with pytest.raises(ValueError):
        reconcile_closed_simulation([], symbol="SPY", starting_cash="1000.001")
    with pytest.raises(ValueError, match="Invalid simulated trade symbol"):
        reconcile_closed_simulation([trade()], symbol="ＳＰＹ")


def test_timezone_equivalent_trade_timestamps_are_supported():
    east = timezone(timedelta(hours=5, minutes=30))
    original = trade()
    offset = replace(
        original, entry_time=original.entry_time.astimezone(east),
        exit_time=original.exit_time.astimezone(east),
    )
    assert reconcile_closed_simulation([offset], symbol="SPY")["net_pnl"] == "18.50"


def test_fractional_cent_slippage_requires_explicit_compatible_assumptions():
    with pytest.raises(ValueError, match="not exact cents"):
        reconcile_closed_simulation([trade(entry=100.10, exit=109.999)], symbol="SPY")
