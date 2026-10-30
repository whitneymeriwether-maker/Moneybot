"""Regression tests: AI JSON confidence must not cross numeric boundaries on parsing."""

import json

import pytest

from v3_proposal_adapter import parse_research_ai_proposal


TRUSTED = ("offline:verified-1",)
BASE = {
    "action": "BUY",
    "thesis": "Hypothetical evidence-backed breakout",
    "risks": "Hypothetical liquidity and reversal risk",
    "evidence_ids": [TRUSTED[0]],
    "confidence": 0.7,
}


def raw_confidence(token):
    """Inject a literal JSON numeric token without float-rounding it in Python."""
    payload = json.dumps(BASE)
    assert '"confidence": 0.7' in payload
    return payload.replace('"confidence": 0.7', f'"confidence": {token}')


@pytest.mark.parametrize("token", [
    "1.0000000000000000000000000000001",
    "-0.0000000000000000000000000000001",
    "1e-9999",
    "-1e-9999",
    "0.999999999999999999999999999999",
    "1e9999999999999999999999999999999999999",
])
def test_confidence_that_would_round_across_a_boundary_fails_closed(token):
    with pytest.raises(ValueError, match="confidence|JSON"):
        parse_research_ai_proposal(
            raw_confidence(token), trusted_evidence_ids=TRUSTED,
        )


@pytest.mark.parametrize("token", [
    "0", "1", "0.7", "0.333333333333333333333333333333",
    "1e-25", "1.0",
])
def test_valid_json_confidence_values_still_parse(token):
    proposal = parse_research_ai_proposal(
        raw_confidence(token), trusted_evidence_ids=TRUSTED,
    )
    assert 0 <= proposal.confidence <= 1
    if token == "1e-25":
        assert proposal.confidence > 0
