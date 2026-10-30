"""Offline adversarial tests for the research-only AI proposal boundary."""

from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from v3_decision import Candidate, PaperAccount, validate_paper_entry
from v3_proposal_adapter import parse_research_ai_proposal


TRUSTED = ("minute:SPY:2026-10-12T13:45:00Z", "filing:abc123")
BASE = {
    "action": "BUY",
    "thesis": "Observed breakout above VWAP",
    "risks": "Liquidity and reversal risk",
    "evidence_ids": [TRUSTED[0]],
    "confidence": 0.7,
}


def parse(fields=None, *, trusted=TRUSTED):
    return parse_research_ai_proposal(
        json.dumps(BASE if fields is None else fields),
        trusted_evidence_ids=trusted,
    )


def test_valid_buy_proposal_is_compatible_with_existing_paper_advisory():
    proposal = parse()
    assert proposal.action == "BUY"
    assert proposal.evidence_ids == (TRUSTED[0],)
    candidate = Candidate(
        "SPY", datetime.now(timezone.utc), 100.0,
        True, True, 2.0, True, 1.0, 0,
    )
    account = PaperAccount(1000, 1000, 0, 0)
    assert validate_paper_entry(candidate, proposal, account).approved


@pytest.mark.parametrize("action", ["WAIT", "REJECT"])
def test_non_buy_proposals_can_carry_no_evidence(action):
    fields = {**BASE, "action": action, "evidence_ids": []}
    assert parse(fields).action == action


def test_buy_cannot_be_approved_without_allowlisted_evidence():
    with pytest.raises(ValueError, match="trusted evidence"):
        parse({**BASE, "evidence_ids": []})


@pytest.mark.parametrize("bad", [
    "invented:123", "minute:SPY:2026-10-12T13:46:00Z",
    " " + TRUSTED[0], TRUSTED[0] + " ", "", "a" * 129,
])
def test_model_cannot_invent_or_mangle_evidence(bad):
    with pytest.raises(ValueError, match="trusted evidence"):
        parse({**BASE, "evidence_ids": [bad]})


def test_multiple_distinct_trusted_ids_are_accepted():
    assert parse({**BASE, "evidence_ids": list(TRUSTED)}).evidence_ids == TRUSTED


@pytest.mark.parametrize("evidence", [
    [TRUSTED[0], TRUSTED[0]], [None], "filing:abc123",
    [TRUSTED[0]] * 17, [True], [123],
])
def test_invalid_evidence_container_and_duplicates_fail(evidence):
    with pytest.raises(ValueError, match="trusted evidence"):
        parse({**BASE, "evidence_ids": evidence})


@pytest.mark.parametrize("trusted", [
    None, [], ("",), (" a",), ("ok", "ok"), ("a" * 129,),
    tuple(str(i) for i in range(129)),
])
def test_untrusted_allowlist_configuration_fails_closed(trusted):
    with pytest.raises(ValueError, match="allowlist"):
        parse(trusted=trusted)


def test_empty_trusted_allowlist_can_only_accept_non_buy_without_evidence():
    assert parse(
        {**BASE, "action": "WAIT", "evidence_ids": []}, trusted=()
    ).action == "WAIT"
    with pytest.raises(ValueError, match="trusted evidence"):
        parse(trusted=())


@pytest.mark.parametrize("invalid", [
    "buy", "HOLD", "SELL", None, 1, True, "",
])
def test_action_must_be_one_of_research_only_actions(invalid):
    with pytest.raises(ValueError, match="action"):
        parse({**BASE, "action": invalid})


@pytest.mark.parametrize("confidence", [
    True, None, "0.7", -0.01, 1.01, 1e999, 10 ** 400,
])
def test_malformed_or_unrepresentable_confidence_fails_closed(confidence):
    with pytest.raises(ValueError, match="confidence"):
        parse({**BASE, "confidence": confidence})


@pytest.mark.parametrize("field", ["thesis", "risks"])
@pytest.mark.parametrize("reason", ["", "  ", None, "x" * 2001, "line\\nnewline"])
def test_reasoning_must_be_bounded_printable_text(field, reason):
    with pytest.raises(ValueError, match="reasoning"):
        parse({**BASE, field: reason})


@pytest.mark.parametrize("invalid", [
    '{"action":"BUY","action":"WAIT","thesis":"x","risks":"x","evidence_ids":[],"confidence":0.5}',
    '{"action":"BUY","thesis":"x","risks":"x","evidence_ids":[],"confidence":NaN}',
    '{"action":"BUY","thesis":"x","risks":"x","evidence_ids":[],"confidence":Infinity}',
    "{broken",
    "[]",
    "null",
])
def test_invalid_json_duplicate_fields_and_nonfinite_constants_fail(invalid):
    with pytest.raises(ValueError):
        parse_research_ai_proposal(invalid, trusted_evidence_ids=TRUSTED)


def test_missing_and_extra_fields_fail():
    for bad in (
        {key: value for key, value in BASE.items() if key != "risks"},
        {**BASE, "order_type": "MARKET"},
    ):
        with pytest.raises(ValueError, match="exactly"):
            parse(bad)


def test_oversized_or_nontext_json_fails():
    with pytest.raises(ValueError, match="size bounds"):
        parse_research_ai_proposal(" " * 16385, trusted_evidence_ids=TRUSTED)
    with pytest.raises(ValueError, match="JSON text"):
        parse_research_ai_proposal(BASE, trusted_evidence_ids=TRUSTED)


def test_duplicate_nested_json_fields_are_rejected_before_schema_check():
    raw = '{"action":"BUY","thesis":"x","risks":"x","evidence_ids":[],"confidence":0.7,"extra":{"x":1,"x":2}}'
    with pytest.raises(ValueError, match="JSON"):
        parse_research_ai_proposal(raw, trusted_evidence_ids=TRUSTED)
