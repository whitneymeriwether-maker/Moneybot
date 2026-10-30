"""Offline regressions: replayed cash highs constrain claimed peak equity."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


PAYLOAD = json.dumps({
    "action": "BUY", "thesis": "Synthetic research breakout",
    "risks": "Synthetic gap and slippage",
    "evidence_ids": ["bar:SPY:1"], "confidence": 0.7,
})


def _past_profit_then_loss(ledger, now):
    # Completed before the current NY trading day: today's realized PnL is 0.
    past = now - timedelta(days=3)
    for event_id, when, side, price in (
        ("buy-profit", past, "BUY", "100.00"),
        ("sell-profit", past + timedelta(seconds=1), "SELL", "150.00"),
        ("buy-loss", past + timedelta(seconds=2), "BUY", "100.00"),
        ("sell-loss", past + timedelta(seconds=3), "SELL", "50.00"),
    ):
        ledger.record_fill(
            event_id=event_id, timestamp=when, symbol="SPY",
            side=side, quantity=1, price=price,
        )


def _review(ledger, now, peak):
    return review_ledger_research_proposal(
        PAYLOAD, ledger=ledger, marks={}, as_of=now,
        peak_equity=peak, realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",),
        candidate=Candidate(
            "SPY", now - timedelta(seconds=1), 100.0,
            True, True, 2.0, True, 1.0, 1,
        ),
    )


@pytest.mark.parametrize("claimed_peak", ["1000.00", "1049.99"])
def test_past_realized_profit_cannot_be_hidden_by_later_loss(tmp_path, claimed_peak):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "historical-cash.sqlite3")
    _past_profit_then_loss(ledger, now)
    before = ledger.snapshot()
    assert before["cash"] == "1000.00"
    assert before["realized_pnl"] == "0.00"
    assert ledger.audit_history()["peak_cash"] == "1050.00"

    result = _review(ledger, now, claimed_peak)
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == "Unverified ledger snapshot or paper risk history"
    assert ledger.snapshot() == before


def test_claimed_peak_at_replayed_cash_high_remains_eligible(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "valid-peak.sqlite3")
    _past_profit_then_loss(ledger, now)
    result = _review(ledger, now, "1050.00")
    assert result.proposal is not None
    assert result.decision.approved
    assert ledger.snapshot()["fill_count"] == 4


def test_open_position_cash_peak_does_not_fabricate_unrealized_high(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "unrealized.sqlite3")
    ledger.record_fill(
        event_id="buy", timestamp=now - timedelta(seconds=30),
        symbol="SPY", side="BUY", quantity=1, price="100.00",
    )
    assert ledger.audit_history()["peak_cash"] == "1000.00"
    assert ledger.snapshot()["cash"] == "900.00"
