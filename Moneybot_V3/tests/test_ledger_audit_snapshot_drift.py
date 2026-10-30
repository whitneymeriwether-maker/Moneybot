"""Offline regressions: ledger audit/mark drift must deny paper advisories."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


@pytest.mark.parametrize("round_trip", [False, True])
def test_intervening_hypothetical_fills_cannot_pass_a_previous_audit(
    tmp_path, monkeypatch, round_trip,
):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "intervening.sqlite3")
    marks = {} if round_trip else {
        "SPY": {"price": "100.00", "timestamp": now}
    }
    original_marked_snapshot = PaperLedger.marked_snapshot

    def intervening_marked_snapshot(self, *args, **kwargs):
        # Deterministically simulate another paper worker recording fills
        # after audit_history() and before the marked account is read.
        stamp = now - timedelta(seconds=2)
        self.record_fill(
            event_id="concurrent-buy", timestamp=stamp,
            symbol="SPY", side="BUY", quantity=1, price="100.00",
        )
        if round_trip:
            # Cash and realized PnL return to their audited values; only
            # the fill count changes, so comparing balances alone fails.
            self.record_fill(
                event_id="concurrent-sell", timestamp=stamp,
                symbol="SPY", side="SELL", quantity=1, price="100.00",
            )
        return original_marked_snapshot(self, *args, **kwargs)

    monkeypatch.setattr(
        PaperLedger, "marked_snapshot", intervening_marked_snapshot,
    )
    payload = json.dumps({
        "action": "BUY", "thesis": "Synthetic research breakout",
        "risks": "Gap and slippage", "evidence_ids": ["bar:SPY:1"],
        "confidence": 0.7,
    })
    candidate = Candidate(
        "SPY", now - timedelta(seconds=1), 100.0,
        True, True, 2.0, True, 1.0, 1,
    )
    result = review_ledger_research_proposal(
        payload, ledger=ledger, marks=marks, as_of=now,
        peak_equity="1000.00", realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",), candidate=candidate,
    )
    assert not result.decision.approved
    assert result.proposal is None
    assert result.decision.reason == (
        "Unverified ledger snapshot or paper risk history"
    )
    assert ledger.audit_history()["audited_fills"] == (2 if round_trip else 1)
    if round_trip:
        assert ledger.snapshot()["cash"] == "1000.00"
        assert ledger.snapshot()["realized_pnl"] == "0.00"
