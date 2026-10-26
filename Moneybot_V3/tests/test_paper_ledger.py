"""Offline persistence and idempotency regression tests for V3 paper ledger."""

import sys
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
