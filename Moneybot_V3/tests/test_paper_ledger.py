"""Offline persistence and idempotency regression tests for V3 paper ledger."""

import sys
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger


T0 = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)


def fill(ledger, event_id="e1", timestamp=T0, symbol="SPY",
         side="BUY", quantity=2, price="100.00", fee="1.00"):
    return ledger.record_fill(
        event_id=event_id, timestamp=timestamp, symbol=symbol,
        side=side, quantity=quantity, price=price, fee=fee,
    )


def test_initial_balance_is_durable_and_cannot_be_reinitialized(tmp_path):
    path = tmp_path / "paper.sqlite3"
    first = PaperLedger(path, starting_cash="1000.00")
    assert first.snapshot() == {
        "starting_cash": "1000.00",
        "cash": "1000.00",
        "realized_pnl": "0.00",
        "positions": {},
        "fill_count": 0,
    }
    assert PaperLedger(path).snapshot() == first.snapshot()
    with pytest.raises(ValueError, match="different starting cash"):
        PaperLedger(path, starting_cash="2000.00")
    assert PaperLedger(path).snapshot() == first.snapshot()


def test_buy_sell_partial_basis_fees_and_restart(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    assert fill(ledger)
    assert ledger.snapshot()["cash"] == "799.00"
    assert ledger.snapshot()["positions"] == {
        "SPY": {"quantity": 2, "cost_basis": "201.00"}
    }
    ledger = PaperLedger(path)
    assert fill(ledger, "e2", T0 + timedelta(minutes=1),
                side="SELL", quantity=1, price="120.00", fee="0.50")
    assert ledger.snapshot()["cash"] == "918.50"
    assert ledger.snapshot()["realized_pnl"] == "19.00"
    assert ledger.snapshot()["positions"]["SPY"] == {
        "quantity": 1, "cost_basis": "100.50"
    }
    assert fill(ledger, "e3", T0 + timedelta(minutes=2),
                side="SELL", quantity=1, price="90.00", fee="0.00")
    assert ledger.snapshot() == {
        "starting_cash": "1000.00",
        "cash": "1008.50",
        "realized_pnl": "8.50",
        "positions": {},
        "fill_count": 3,
    }


def test_exact_retry_is_noop_across_restarts_and_timezones(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    assert fill(ledger)
    other = PaperLedger(path)
    local = T0.astimezone(ZoneInfo("America/New_York"))
    assert fill(other, timestamp=local) is False
    assert other.snapshot()["fill_count"] == 1
    assert other.snapshot()["cash"] == "799.00"


def test_conflicting_event_id_rejected_without_mutation(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="Conflicting"):
        fill(ledger, price="101.00")
    assert ledger.snapshot() == before


def test_cash_cannot_be_overdrawn_and_failed_fill_is_not_recorded(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError, match="Insufficient"):
        fill(ledger, price="600.00")
    assert ledger.snapshot()["fill_count"] == 0
    assert ledger.snapshot()["cash"] == "1000.00"
    assert fill(ledger)  # Failed ID did not poison idempotency.


def test_cannot_short_or_sell_more_than_owned(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError, match="unowned"):
        fill(ledger, side="SELL")
    fill(ledger)
    with pytest.raises(ValueError, match="unowned"):
        fill(ledger, event_id="e2", side="SELL", quantity=3)
    assert ledger.snapshot()["positions"]["SPY"]["quantity"] == 2
    assert ledger.snapshot()["fill_count"] == 1


def test_partial_sales_allocate_every_cent_of_cost_basis(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger, quantity=3, price="0.01", fee="0.01")
    fill(ledger, "e2", T0 + timedelta(minutes=1),
         side="SELL", quantity=1, price="0.01", fee="0.00")
    assert ledger.snapshot()["positions"]["SPY"]["cost_basis"] == "0.03"
    fill(ledger, "e3", T0 + timedelta(minutes=2),
         side="SELL", quantity=1, price="0.01", fee="0.00")
    assert ledger.snapshot()["positions"]["SPY"]["cost_basis"] == "0.01"
    fill(ledger, "e4", T0 + timedelta(minutes=3),
         side="SELL", quantity=1, price="0.01", fee="0.00")
    assert ledger.snapshot()["positions"] == {}
    assert ledger.snapshot()["realized_pnl"] == "-0.01"
    assert ledger.snapshot()["cash"] == "999.99"


def test_fee_cannot_exceed_sale_proceeds(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger, quantity=1, price="1.00", fee="0.00")
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="proceeds"):
        fill(ledger, "e2", T0 + timedelta(minutes=1),
             side="SELL", quantity=1, price="1.00", fee="2.00")
    assert ledger.snapshot() == before


def test_rejects_backdated_new_fills_without_affecting_replay(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger, timestamp=T0 + timedelta(minutes=1))
    with pytest.raises(ValueError, match="Backdated"):
        fill(ledger, "e2", T0)
    assert fill(ledger, timestamp=T0 + timedelta(minutes=1)) is False
    assert ledger.snapshot()["fill_count"] == 1


def test_two_symbols_and_same_timestamp_are_supported(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger, quantity=1, fee="0.00")
    fill(ledger, event_id="e2", symbol="QQQ", quantity=1, fee="0.00")
    assert list(ledger.snapshot()["positions"]) == ["QQQ", "SPY"]
    assert ledger.snapshot()["cash"] == "800.00"


@pytest.mark.parametrize("invalid", [
    100.0, 100, True, "NaN", "Infinity", "-1.00", "0.00",
    "1.001", "1e100", Decimal("NaN"), "not money",
])
def test_rejects_invalid_price_without_recording(tmp_path, invalid):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError):
        fill(ledger, price=invalid)
    assert ledger.snapshot()["fill_count"] == 0


@pytest.mark.parametrize("invalid", [
    -1, 0.001, "NaN", "Infinity", 1.0, "1e100",
])
def test_rejects_invalid_fee_without_recording(tmp_path, invalid):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError):
        fill(ledger, fee=invalid)
    assert ledger.snapshot()["fill_count"] == 0


@pytest.mark.parametrize("kwargs", [
    {"event_id": "bad event"},
    {"event_id": ""},
    {"symbol": "spy"},
    {"symbol": "SPY;DROP"},
    {"side": "buy"},
    {"side": "SHORT"},
    {"quantity": True},
    {"quantity": 0},
    {"quantity": -1},
    {"quantity": 1.5},
    {"quantity": 10**10},
    {"timestamp": datetime(2026, 10, 26, 14, 30)},
])
def test_rejects_malformed_fill_fields(tmp_path, kwargs):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError):
        fill(ledger, **kwargs)
    assert ledger.snapshot()["fill_count"] == 0


def test_concurrent_duplicate_event_is_applied_exactly_once(tmp_path):
    path = tmp_path / "paper.sqlite3"
    PaperLedger(path)
    def submit(_):
        return fill(PaperLedger(path))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, range(4)))
    assert results.count(True) == 1
    assert results.count(False) == 3
    assert PaperLedger(path).snapshot()["cash"] == "799.00"
    assert PaperLedger(path).snapshot()["fill_count"] == 1


def test_file_path_and_starting_cash_must_be_valid(tmp_path):
    with pytest.raises(ValueError):
        PaperLedger(":memory:")
    with pytest.raises(ValueError):
        PaperLedger(tmp_path / "paper.sqlite3", starting_cash=0.0)
    with pytest.raises(ValueError):
        PaperLedger(tmp_path / "paper.sqlite3", starting_cash="-10.00")


@pytest.mark.parametrize("table, column, delta", [
    ("paper_account", "cash_cents", 1),
    ("paper_positions", "cost_basis_cents", 1),
    ("paper_account", "realized_pnl_cents", 1),
])
def test_corrupted_persisted_account_fails_closed(tmp_path, table, column, delta):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    fill(ledger, "e2", T0 + timedelta(minutes=1),
         side="SELL", quantity=1, price="110.00", fee="0.00")
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE {table} SET {column} = {column} + ?", (delta,))
    with pytest.raises(ValueError, match="accounting invariant"):
        ledger.snapshot()
    with pytest.raises(ValueError, match="accounting invariant"):
        fill(ledger, "e3", T0 + timedelta(minutes=2), quantity=1)
    # Even a byte-for-byte retry cannot acknowledge a corrupted ledger.
    with pytest.raises(ValueError, match="accounting invariant"):
        fill(ledger)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == 2


def test_multiple_positions_preserve_accounting_invariant(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger, quantity=2, price="100.00", fee="1.00")
    fill(ledger, "e2", T0 + timedelta(minutes=1),
         symbol="QQQ", quantity=3, price="50.00", fee="0.25")
    fill(ledger, "e3", T0 + timedelta(minutes=2),
         side="SELL", quantity=1, price="110.00", fee="0.50")
    snapshot = ledger.snapshot()
    cash = Decimal(snapshot["cash"])
    basis = sum(Decimal(pos["cost_basis"]) for pos in snapshot["positions"].values())
    realized = Decimal(snapshot["realized_pnl"])
    assert cash + basis - realized == Decimal(snapshot["starting_cash"])
    assert snapshot["fill_count"] == 3


def test_history_audit_replays_partial_fills_and_same_timestamp(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    assert ledger.audit_history() == {
        "audited_fills": 0, "cash": "1000.00", "realized_pnl": "0.00"
    }
    fill(ledger, event_id="z-buy", quantity=3, price="10.00", fee="0.01")
    # An alphabetically earlier sell ID must not reorder same-time fills.
    fill(ledger, event_id="a-sell", side="SELL", quantity=1,
         price="12.00", fee="0.02")
    fill(ledger, event_id="other", symbol="QQQ", quantity=2,
         price="20.00", fee="0.00")
    assert PaperLedger(path).audit_history() == {
        "audited_fills": 3, "cash": "941.97", "realized_pnl": "1.98"
    }


def test_history_audit_catches_coordinated_balance_corruption(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    with sqlite3.connect(path) as db:
        # Basic cash + basis - realized reconciliation still passes.
        db.execute("""UPDATE paper_account SET
                      cash_cents=cash_cents+1,
                      realized_pnl_cents=realized_pnl_cents+1""")
    assert ledger.snapshot()["cash"] == "799.01"
    with pytest.raises(ValueError, match="fill history: state mismatch"):
        ledger.audit_history()


@pytest.mark.parametrize("sql", [
    "UPDATE paper_fills SET price_cents=price_cents+1 WHERE event_id='e1'",
    "UPDATE paper_fills SET timestamp_utc='not-a-timestamp' WHERE event_id='e1'",
    "UPDATE paper_fills SET symbol='INVALID SYMBOL' WHERE event_id='e1'",
    "DELETE FROM paper_fills WHERE event_id='e1'",
])
def test_history_audit_detects_changed_or_missing_fill_records(tmp_path, sql):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    with sqlite3.connect(path) as db:
        db.execute(sql)
    # Account-level invariant alone cannot verify fill provenance.
    assert ledger.snapshot()["cash"] == "799.00"
    with pytest.raises(ValueError, match="Corrupt paper fill history"):
        ledger.audit_history()


def test_history_audit_detects_nonmonotonic_fill_timestamps(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    fill(ledger, event_id="e2", timestamp=T0 + timedelta(minutes=1),
         symbol="QQQ", quantity=1, fee="0.00")
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE paper_fills SET timestamp_utc=? WHERE event_id='e2'",
            ((T0 - timedelta(minutes=1)).isoformat(timespec="microseconds"),)
        )
    with pytest.raises(ValueError, match="fill history: timestamp"):
        ledger.audit_history()


def test_marked_snapshot_empty_account_is_read_only(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    before = ledger.snapshot()
    marked = ledger.marked_snapshot({}, as_of=T0)
    assert marked["cash"] == "1000.00"
    assert marked["equity"] == "1000.00"
    assert marked["market_value"] == "0.00"
    assert marked["unrealized_pnl"] == "0.00"
    assert marked["total_pnl"] == "0.00"
    assert marked["gross_exposure_pct"] == "0.0000"
    assert marked["positions"] == {}
    assert ledger.snapshot() == before


def test_marked_snapshot_values_fee_adjusted_basis_and_open_exposure(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    as_of = T0 + timedelta(minutes=1)
    before = ledger.snapshot()
    marked = ledger.marked_snapshot(
        {"SPY": {"price": "110.00", "timestamp": as_of}}, as_of=as_of
    )
    assert marked["cash"] == "799.00"
    assert marked["market_value"] == "220.00"
    assert marked["equity"] == "1019.00"
    assert marked["realized_pnl"] == "0.00"
    assert marked["unrealized_pnl"] == "19.00"
    assert marked["total_pnl"] == "19.00"
    assert marked["gross_exposure_pct"] == "21.5898"
    assert marked["positions"]["SPY"] == {
        "quantity": 2, "cost_basis": "201.00", "mark_price": "110.00",
        "mark_timestamp_utc": as_of.isoformat(timespec="microseconds"),
        "market_value": "220.00", "unrealized_pnl": "19.00",
    }
    assert ledger.snapshot() == before


def test_marked_snapshot_reconciles_realized_and_unrealized_pnl(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    fill(ledger, "sell", T0 + timedelta(minutes=1), side="SELL",
         quantity=1, price="120.00", fee="0.50")
    at = T0 + timedelta(minutes=2)
    marked = ledger.marked_snapshot(
        {"SPY": {"price": "110.00", "timestamp": at}}, as_of=at
    )
    assert marked["cash"] == "918.50"
    assert marked["realized_pnl"] == "19.00"
    assert marked["unrealized_pnl"] == "9.50"
    assert marked["equity"] == "1028.50"
    assert marked["total_pnl"] == "28.50"
    assert marked["gross_exposure_pct"] == "10.6952"


@pytest.mark.parametrize("marks", [
    {},
    {"QQQ": {"price": "100.00", "timestamp": T0}},
    {"SPY": {"price": "100.00", "timestamp": T0},
     "QQQ": {"price": "100.00", "timestamp": T0}},
    {"SPY": {"price": "100.00"}},
    {"SPY": {"price": "100.00", "timestamp": T0, "volume": 1}},
    {"SPY": {"price": 100.0, "timestamp": T0}},
    {"SPY": {"price": "0.00", "timestamp": T0}},
    {"SPY": {"price": "NaN", "timestamp": T0}},
    {"SPY": {"price": "100.001", "timestamp": T0}},
    {"SPY": {"price": "100.00", "timestamp": datetime(2026, 10, 26, 14, 30)}},
])
def test_marked_snapshot_rejects_missing_extra_or_malformed_marks(tmp_path, marks):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    before = ledger.snapshot()
    with pytest.raises(ValueError):
        ledger.marked_snapshot(marks, as_of=T0 + timedelta(minutes=1))
    assert ledger.snapshot() == before


@pytest.mark.parametrize("timestamp,as_of,max_age", [
    (T0, T0 + timedelta(minutes=13), 720),
    (T0 + timedelta(seconds=1), T0, 720),
    (T0 - timedelta(seconds=1), T0, 720),
    (T0, T0, -1),
    (T0, T0, True),
    (T0, T0, 86401),
    (T0, datetime(2026, 10, 26, 14, 30), 720),
])
def test_marked_snapshot_rejects_stale_future_and_pre_fill_marks(
    tmp_path, timestamp, as_of, max_age
):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    with pytest.raises(ValueError):
        ledger.marked_snapshot(
            {"SPY": {"price": "100.00", "timestamp": timestamp}},
            as_of=as_of, max_age_seconds=max_age,
        )


def test_marked_snapshot_rejects_as_of_before_latest_other_fill(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    fill(ledger, "e2", T0 + timedelta(minutes=1),
         symbol="QQQ", price="10.00", fee="0.00")
    with pytest.raises(ValueError, match="predates a recorded fill"):
        ledger.marked_snapshot(
            {"SPY": {"price": "100.00", "timestamp": T0},
             "QQQ": {"price": "10.00", "timestamp": T0}},
            as_of=T0,
        )


def test_marked_snapshot_normalizes_timezone_offsets(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    fill(ledger)
    at = T0 + timedelta(minutes=1)
    eastern = at.astimezone(ZoneInfo("America/New_York"))
    marked = ledger.marked_snapshot(
        {"SPY": {"price": Decimal("100.00"), "timestamp": eastern}},
        as_of=eastern,
    )
    assert marked["as_of_utc"] == at.isoformat(timespec="microseconds")
    assert marked["positions"]["SPY"]["mark_timestamp_utc"] == marked["as_of_utc"]


def test_marked_snapshot_rejects_corrupt_persisted_balances(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE paper_account SET cash_cents=cash_cents+1")
    with pytest.raises(ValueError, match="accounting invariant"):
        ledger.marked_snapshot(
            {"SPY": {"price": "100.00", "timestamp": T0}}, as_of=T0
        )


@pytest.mark.parametrize("sql", [
    "UPDATE paper_positions SET symbol='INVALID SYMBOL' WHERE symbol='SPY'",
    "UPDATE paper_positions SET symbol='spy' WHERE symbol='SPY'",
    """UPDATE paper_positions SET cost_basis_cents=0 WHERE symbol='SPY';
    UPDATE paper_account SET realized_pnl_cents=-20100 WHERE id=1""",
])
def test_invalid_persisted_position_fails_closed_even_if_balances_reconcile(tmp_path, sql):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path)
    fill(ledger)
    before_count = ledger.snapshot()["fill_count"]
    with sqlite3.connect(path) as db:
        db.executescript(sql)
    with pytest.raises(ValueError, match="Corrupt paper position"):
        ledger.snapshot()
    with pytest.raises(ValueError, match="Corrupt paper position"):
        fill(ledger, event_id="e2", timestamp=T0 + timedelta(minutes=1))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] == before_count
