"""Offline regression tests for a fully depleted, flat V3 paper account."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger


T0 = datetime(2026, 10, 28, 13, 30, tzinfo=timezone.utc)


def depleted_ledger(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(path, starting_cash="100.00")
    assert ledger.record_fill(
        event_id="buy", timestamp=T0, symbol="SPY",
        side="BUY", quantity=1, price="100.00",
    )
    # The full sale proceeds are consumed by the exit fee, leaving no
    # position and exactly zero cash, without violating any cash limit.
    assert ledger.record_fill(
        event_id="sell", timestamp=T0 + timedelta(minutes=1),
        symbol="SPY", side="SELL", quantity=1,
        price="1.00", fee="1.00",
    )
    return ledger, path


def test_zero_equity_flat_account_is_a_valid_marked_snapshot(tmp_path):
    ledger, path = depleted_ledger(tmp_path)
    before = ledger.snapshot()
    assert before["cash"] == "0.00"
    assert before["positions"] == {}
    assert ledger.audit_history()["audited_fills"] == 2

    at = T0 + timedelta(minutes=2)
    marked = ledger.marked_snapshot({}, as_of=at)
    assert marked["equity"] == "0.00"
    assert marked["cash"] == "0.00"
    assert marked["market_value"] == "0.00"
    assert marked["realized_pnl"] == "-100.00"
    assert marked["unrealized_pnl"] == "0.00"
    assert marked["total_pnl"] == "-100.00"
    assert marked["gross_exposure_pct"] == "0.0000"
    assert marked["positions"] == {}
    assert marked["fill_count"] == 2
    assert ledger.snapshot() == before

    reopened = PaperLedger(path, starting_cash="100.00")
    assert reopened.marked_snapshot({}, as_of=at) == marked


def test_depleted_account_still_rejects_backdated_marked_snapshot(tmp_path):
    ledger, _ = depleted_ledger(tmp_path)
    with pytest.raises(ValueError, match="predates a recorded fill"):
        ledger.marked_snapshot({}, as_of=T0)


def test_depleted_account_still_rejects_extra_mark_and_new_purchase(tmp_path):
    ledger, _ = depleted_ledger(tmp_path)
    at = T0 + timedelta(minutes=2)
    with pytest.raises(ValueError, match="exactly match"):
        ledger.marked_snapshot(
            {"SPY": {"price": "1.00", "timestamp": at}}, as_of=at
        )
    with pytest.raises(ValueError, match="Insufficient hypothetical paper cash"):
        ledger.record_fill(
            event_id="buy-again", timestamp=at, symbol="SPY",
            side="BUY", quantity=1, price="0.01",
        )
    assert ledger.snapshot()["fill_count"] == 2
