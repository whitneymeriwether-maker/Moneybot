"""Offline tests: ledger-backed AI review is read-only and fails closed."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from paper_ledger import PaperLedger
from v3_decision import Candidate, RiskPolicy
from v3_ledger_advisory import review_ledger_research_proposal


TRUSTED = ("bar:SPY:1",)


def _payload(action="BUY", evidence=None):
    return json.dumps({
        "action": action,
        "thesis": "Synthetic observed breakout",
        "risks": "Gap and slippage",
        "evidence_ids": ["bar:SPY:1"] if evidence is None else evidence,
        "confidence": 0.7,
    })


def _candidate(timestamp):
    return Candidate("SPY", timestamp, 100.0, True, True, 2.0, True, 1.0, 0)


def _review(tmp_path, *, with_position=False, **overrides):
    now = datetime.now(timezone.utc)
    ledger = PaperLedger(tmp_path / "paper.sqlite3", starting_cash="1000.00")
    marks = {}
    if with_position:
        ledger.record_fill(
            event_id="offline-buy", timestamp=now - timedelta(seconds=30),
            symbol="SPY", side="BUY", quantity=1, price="100.00",
        )
        marks = {
            "SPY": {
                "price": "100.00",
                "timestamp": now - timedelta(seconds=5),
            }
        }
    inputs = dict(
        payload=_payload(), ledger=ledger, marks=marks, as_of=now,
        peak_equity="1000.00", realized_pnl_today="0.00",
        trusted_evidence_ids=TRUSTED,
        candidate=_candidate(now - timedelta(seconds=1)),
    )
    inputs.update(overrides)
    before = ledger.snapshot()
    result = review_ledger_research_proposal(**inputs)
    assert ledger.snapshot() == before  # No hypothetical fill, even on BUY.
    return result


def test_empty_ledger_can_support_a_read_only_buy_advisory(tmp_path):
    result = _review(tmp_path)
    assert result.proposal.action == "BUY"
    assert result.decision.approved
    assert result.decision.quantity == 5


def test_open_position_is_included_in_exposure_and_cash_sizing(tmp_path):
    result = _review(tmp_path, with_position=True)
    assert result.decision.approved
    assert result.decision.quantity == 4


@pytest.mark.parametrize("field,value", [
    ("peak_equity", "999.99"),
    ("peak_equity", "NaN"),
    ("peak_equity", "1000.001"),
    ("peak_equity", 1000.0),
    ("peak_equity", "-1000.00"),
    ("realized_pnl_today", "-0.001"),
    ("realized_pnl_today", float("nan")),
    ("realized_pnl_today", "Infinity"),
])
def test_malformed_or_understated_risk_history_denies_without_a_fill(tmp_path, field, value):
    result = _review(tmp_path, **{field: value})
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == "Unverified ledger snapshot or paper risk history"


def test_daily_loss_context_still_triggers_independent_gate(tmp_path):
    result = _review(tmp_path, realized_pnl_today="-30.00")
    assert result.proposal is not None
    assert not result.decision.approved
    assert result.decision.reason == "Daily realized-loss circuit breaker"


@pytest.mark.parametrize("offset", [-3600, 60])
def test_stale_or_future_account_as_of_denies(tmp_path, offset):
    now = datetime.now(timezone.utc)
    result = _review(tmp_path, as_of=now + timedelta(seconds=offset))
    assert not result.decision.approved
    assert result.proposal is None


def test_account_snapshot_must_not_predate_candidate_observation(tmp_path):
    now = datetime.now(timezone.utc)
    result = _review(
        tmp_path, as_of=now - timedelta(seconds=20),
        candidate=_candidate(now),
    )
    assert not result.decision.approved
    assert result.proposal is None


def test_unmarked_position_cannot_be_silently_ignored(tmp_path):
    result = _review(tmp_path, with_position=True, marks={})
    assert not result.decision.approved
    assert result.proposal is None


def test_future_mark_cannot_be_used_as_paper_account_equity(tmp_path):
    now = datetime.now(timezone.utc)
    result = _review(
        tmp_path, with_position=True,
        marks={"SPY": {"price": "100.00", "timestamp": now + timedelta(hours=1)}},
    )
    assert not result.decision.approved
    assert result.proposal is None


def test_invalid_ai_payload_does_not_become_a_ledger_fill(tmp_path):
    result = _review(tmp_path, payload=_payload(evidence=["invented"]))
    assert not result.decision.approved
    assert result.proposal is None
    assert result.decision.reason == "Invalid research AI proposal or evidence"


@pytest.mark.parametrize("action", ["WAIT", "REJECT"])
def test_non_buy_proposals_remain_denials(tmp_path, action):
    result = _review(tmp_path, payload=_payload(action=action, evidence=[]))
    assert result.proposal.action == action
    assert not result.decision.approved


def test_invalid_risk_policy_fails_closed_before_reading_ledger(tmp_path):
    result = _review(tmp_path, policy=RiskPolicy(max_exposure=1.5))
    assert result.proposal is None
    assert not result.decision.approved


def test_non_ledger_object_cannot_impersonate_a_paper_account(tmp_path):
    class FakeLedger:
        def marked_snapshot(self, *args, **kwargs):
            raise AssertionError("Fake ledger must not be accessed")
    result = _review(tmp_path, ledger=FakeLedger())
    assert result.proposal is None
    assert not result.decision.approved
