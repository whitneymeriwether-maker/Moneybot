"""Offline regression: candidate prices reconcile with held-position marks."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


PAYLOAD = json.dumps({
    "action": "BUY",
    "thesis": "Synthetic breakout",
    "risks": "Synthetic gap and slippage",
    "evidence_ids": ["bar:SPY:1"],
    "confidence": 0.7,
})


def _review(tmp_path, *, candidate_symbol="SPY", candidate_price=100.0,
            held_symbol="SPY"):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "reconcile.sqlite3")
    ledger.record_fill(
        event_id="held-position",
        timestamp=now - timedelta(seconds=60),
        symbol=held_symbol, side="BUY", quantity=1, price="100.00",
    )
    before = ledger.snapshot()
    result = review_ledger_research_proposal(
        PAYLOAD, ledger=ledger,
        marks={
            held_symbol: {
                "price": "100.00",
                "timestamp": now - timedelta(seconds=1),
            },
        },
        as_of=now,
        peak_equity="1000.00",
        realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",),
        candidate=Candidate(
            candidate_symbol, now - timedelta(seconds=1),
            candidate_price, True, True, 2.0, True, 1.0, 1,
        ),
    )
    assert ledger.snapshot() == before
    return result


def test_matching_signal_and_held_mark_remains_eligible(tmp_path):
    result = _review(tmp_path)
    assert result.proposal is not None
    assert result.decision.approved


@pytest.mark.parametrize("signal_price", [99.99, 100.01, 95.0, 105.0])
def test_divergent_held_signal_price_fails_closed(tmp_path, signal_price):
    result = _review(tmp_path, candidate_price=signal_price)
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == (
        "Unverified ledger snapshot or paper risk history"
    )


def test_unheld_candidate_does_not_require_an_existing_position_mark(tmp_path):
    result = _review(tmp_path, candidate_symbol="SPY", held_symbol="QQQ")
    assert result.proposal is not None
    assert result.decision.approved


def test_nonfinite_held_candidate_price_fails_closed(tmp_path):
    result = _review(tmp_path, candidate_price=float("nan"))
    assert result.proposal is None
    assert not result.decision.approved
