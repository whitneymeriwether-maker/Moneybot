"""Offline integration checks for the untrusted-JSON paper advisory bridge."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from v3_decision import Candidate, PaperAccount, RiskPolicy
from v3_research_advisory import ResearchReview, review_research_proposal


def candidate():
    return Candidate(
        "SPY", datetime.now(timezone.utc), 100.0,
        True, True, 2.0, True, 1.0, 0,
    )


ACCOUNT = PaperAccount(1000, 1000, 0, 0)
TRUSTED = ("bar:SPY:1", "filing:SPY:2")


def payload(action="BUY", evidence=None, **changes):
    data = {
        "action": action,
        "thesis": "Observed synthetic breakout",
        "risks": "Reversal and liquidity",
        "evidence_ids": ["bar:SPY:1"] if evidence is None else evidence,
        "confidence": 0.7,
    }
    data.update(changes)
    return json.dumps(data)


def review(raw, **changes):
    inputs = {
        "trusted_evidence_ids": TRUSTED,
        "candidate": candidate(),
        "account": ACCOUNT,
    }
    inputs.update(changes)
    return review_research_proposal(raw, **inputs)


def test_buy_json_passes_through_independent_paper_gate_without_fill():
    result = review(payload())
    assert isinstance(result, ResearchReview)
    assert result.proposal.action == "BUY"
    assert result.proposal.evidence_ids == ("bar:SPY:1",)
    assert result.decision.approved
    assert result.decision.quantity == 5
    assert result.decision.reason == "Approved for paper simulation only"


@pytest.mark.parametrize("action", ["WAIT", "REJECT"])
def test_nonbuy_json_is_retained_for_audit_but_never_approved(action):
    result = review(payload(action, evidence=[]))
    assert result.proposal.action == action
    assert result.proposal.evidence_ids == ()
    assert not result.decision.approved
    assert result.decision.quantity == 0
    assert result.decision.reason == f"AI decision: {action}"


@pytest.mark.parametrize("raw", [
    "",
    "{",
    "null",
    "[]",
    '{"action":"BUY","action":"WAIT"}',
    '{"action":"SELL"}',
    "x" * 16385,
    payload(evidence=["invented:1"]),
    payload(evidence=[]),
    payload(confidence=-0.1),
    payload(thesis="Hidden" + chr(0x202e) + "override"),
])
def test_invalid_model_payload_fails_closed_without_echo(raw):
    result = review(raw)
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.quantity == 0
    assert result.decision.reason == "Invalid research AI proposal or evidence"


@pytest.mark.parametrize("allowlist", [
    None,
    ["bar:SPY:1"],
    ("bar:SPY:1", "bar:SPY:1"),
    ("bar:SPY:1" + chr(0x200b),),
    tuple(f"source:{i}" for i in range(129)),
])
def test_untrusted_or_malformed_allowlist_fails_closed(allowlist):
    result = review(payload(), trusted_evidence_ids=allowlist)
    assert result.proposal is None
    assert not result.decision.approved
    assert result.decision.reason == "Invalid research AI proposal or evidence"


def test_buy_requires_matching_allowlist_even_with_valid_json():
    result = review(payload(), trusted_evidence_ids=("filing:SPY:2",))
    assert result.proposal is None
    assert not result.decision.approved


def test_valid_buy_does_not_bypass_independent_stale_data_gate():
    stale = replace(
        candidate(), timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    result = review(payload(), candidate=stale)
    assert result.proposal is not None
    assert not result.decision.approved
    assert result.decision.reason == "Stale or future market timestamp"


def test_valid_buy_does_not_bypass_daily_loss_circuit_breaker():
    account = replace(ACCOUNT, realized_pnl_today=-30)
    result = review(payload(), account=account)
    assert result.proposal is not None
    assert not result.decision.approved
    assert result.decision.reason == "Daily realized-loss circuit breaker"


def test_valid_buy_does_not_bypass_risk_policy_validation():
    result = review(payload(), policy=RiskPolicy(max_exposure=1.5))
    assert result.proposal is not None
    assert not result.decision.approved
    assert result.decision.reason == "Invalid risk policy"


def test_valid_buy_does_not_bypass_breakout_requirement():
    result = review(payload(), candidate=replace(candidate(), above_vwap=False))
    assert result.proposal is not None
    assert not result.decision.approved
    assert result.decision.reason == "Opening-range breakout criteria not satisfied"


def test_payload_is_never_used_as_evidence_allowlist():
    # A model can cite a plausible ID but cannot authorize its own source.
    result = review(payload(), trusted_evidence_ids=())
    assert result.proposal is None
    assert not result.decision.approved


def test_non_string_payload_cannot_be_interpolated_into_denial():
    class Untrusted:
        def __str__(self):
            raise AssertionError("Untrusted payload must not be stringified")

    result = review(Untrusted())
    assert result.proposal is None
    assert result.decision.reason == "Invalid research AI proposal or evidence"
