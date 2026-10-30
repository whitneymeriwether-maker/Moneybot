"""Offline regression: marked paper exposure cannot predate a new signal."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate
from v3_ledger_advisory import review_ledger_research_proposal


PROPOSAL = json.dumps({
    "action": "BUY",
    "thesis": "Synthetic opening-range breakout",
    "risks": "Synthetic gap and slippage",
    "evidence_ids": ["bar:SPY:1"],
    "confidence": 0.7,
})


def _review(ledger, now, marks):
    before = ledger.snapshot()
    result = review_ledger_research_proposal(
        PROPOSAL,
        ledger=ledger,
        marks=marks,
        as_of=now,
        peak_equity="1000.00",
        realized_pnl_today="0.00",
        trusted_evidence_ids=("bar:SPY:1",),
        candidate=Candidate(
            "SPY", now - timedelta(seconds=1), 100.0,
            True, True, 2.0, True, 1.0, 1,
        ),
    )
    assert ledger.snapshot() == before
    return result


@pytest.mark.parametrize("mark_offset,approved", [
    (-3, True),
    (-6, True),   # Exactly five seconds before the candidate.
    (-7, False),  # Older than the five-second cross-feed allowance.
    (-20, False), # Fresh under the 12-minute policy, but not for this signal.
])
def test_mark_chronology_is_bound_to_signal_not_only_as_of(
    tmp_path, mark_offset, approved,
):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    ledger.record_fill(
        event_id="buy-spy",
        timestamp=now - timedelta(seconds=90),
        symbol="SPY",
        side="BUY",
        quantity=1,
        price="100.00",
    )
    result = _review(ledger, now, {
        "SPY": {
            "price": "100.00",
            "timestamp": now + timedelta(seconds=mark_offset),
        },
    })
    assert result.decision.approved is approved
    if approved:
        assert result.proposal is not None
        assert result.decision.quantity > 0
    else:
        assert result.proposal is None
        assert result.decision.reason == (
            "Unverified ledger snapshot or paper risk history"
        )


def test_one_older_position_mark_denies_entire_account_review(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "two-positions.sqlite3")
    for symbol in ("SPY", "QQQ"):
        ledger.record_fill(
            event_id="buy-" + symbol.lower(),
            timestamp=now - timedelta(seconds=90),
            symbol=symbol,
            side="BUY",
            quantity=1,
            price="100.00",
        )
    result = _review(ledger, now, {
        "SPY": {"price": "100.00", "timestamp": now - timedelta(seconds=2)},
        "QQQ": {"price": "100.00", "timestamp": now - timedelta(seconds=20)},
    })
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == (
        "Unverified ledger snapshot or paper risk history"
    )
