"""Offline regressions: a read-only ledger advisory must exclude fill drift."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


def _review(ledger, now):
    payload = json.dumps({
        "action": "BUY", "thesis": "Synthetic research breakout",
        "risks": "Gap and slippage", "evidence_ids": ["bar:SPY:1"],
        "confidence": 0.7,
    })
    candidate = Candidate(
        "SPY", now - timedelta(seconds=1), 100.0,
        True, True, 2.0, True, 1.0, 1,
    )
    return review_ledger_research_proposal(
        payload, ledger=ledger, marks={}, as_of=now,
        peak_equity="1000.00", realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",), candidate=candidate,
    )


@pytest.mark.parametrize("attempted_writes", [1, 2])
def test_competing_sqlite_writer_cannot_interleave_audit_and_marks(
    tmp_path, monkeypatch, attempted_writes,
):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "intervening.sqlite3")
    original_marked_snapshot = PaperLedger.marked_snapshot
    observed = []

    def competing_marked_snapshot(self, *args, **kwargs):
        # This callback runs after audit_history() but before the mark read.
        # A separate SQLite connection must not acquire a write reservation.
        for _ in range(attempted_writes):
            with sqlite3.connect(self.db_path, timeout=0, isolation_level=None) as db:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    db.execute("BEGIN IMMEDIATE")
                observed.append("writer blocked")
        return original_marked_snapshot(self, *args, **kwargs)

    monkeypatch.setattr(
        PaperLedger, "marked_snapshot", competing_marked_snapshot,
    )
    result = _review(ledger, now)
    assert observed == ["writer blocked"] * attempted_writes
    assert result.decision.approved
    assert result.proposal.action == "BUY"
    assert ledger.audit_history()["audited_fills"] == 0

    # The reservation is released after review, without writing a fill.
    ledger.record_fill(
        event_id="post-review", timestamp=now - timedelta(seconds=1),
        symbol="SPY", side="BUY", quantity=1, price="100.00",
    )
    assert ledger.audit_history()["audited_fills"] == 1


def test_advisory_read_reservation_releases_on_exception(tmp_path):
    ledger = PaperLedger(tmp_path / "release.sqlite3")
    with pytest.raises(RuntimeError, match="test failure"):
        with ledger.consistent_advisory_read():
            raise RuntimeError("test failure")
    assert ledger.snapshot()["fill_count"] == 0
    ledger.record_fill(
        event_id="after-exception", timestamp=datetime.now(timezone.utc),
        symbol="SPY", side="BUY", quantity=1, price="100.00",
    )
    assert ledger.audit_history()["audited_fills"] == 1
