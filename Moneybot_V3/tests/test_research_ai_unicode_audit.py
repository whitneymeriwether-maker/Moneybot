"""Nonprinting Unicode must not obscure AI audit reasoning or evidence IDs."""

import json

import pytest

from v3_proposal_adapter import parse_research_ai_proposal


BASE = {
    "action": "BUY",
    "thesis": "Observed hypothetical breakout",
    "risks": "Hypothetical liquidity risk",
    "evidence_ids": ["snapshot:1"],
    "confidence": 0.5,
}

# Includes DEL, C1 control, zero-width format, bidirectional override,
# line/paragraph separators, and a JSON-escaped unpaired surrogate.
NONPRINTING = (
    "\x7f", "\x85", "\u200b", "\u202e", "\u2028", "\u2029", "\ud800",
)


@pytest.mark.parametrize("field", ("thesis", "risks"))
@pytest.mark.parametrize("hidden", NONPRINTING)
def test_hidden_unicode_in_reasoning_is_rejected(field, hidden):
    proposal = {**BASE, field: "Audit " + hidden + " text"}
    # ensure_ascii=True permits the parser to encounter escaped surrogates;
    # a raw surrogate would already fail the UTF-8 payload check.
    payload = json.dumps(proposal, ensure_ascii=True)
    with pytest.raises(ValueError, match="reasoning"):
        parse_research_ai_proposal(
            payload, trusted_evidence_ids=("snapshot:1",),
        )


@pytest.mark.parametrize("hidden", NONPRINTING)
def test_trusted_evidence_allowlist_rejects_hidden_unicode(hidden):
    identifier = "snapshot:" + hidden + "1"
    proposal = {**BASE, "evidence_ids": [identifier]}
    with pytest.raises(ValueError, match="allowlist"):
        parse_research_ai_proposal(
            json.dumps(proposal, ensure_ascii=True),
            trusted_evidence_ids=(identifier,),
        )


def test_readable_international_reasoning_remains_accepted():
    proposal = {
        **BASE,
        "thesis": "Risque étudié; 市场观察",
        "risks": "Reversão possível; 风险提示",
    }
    result = parse_research_ai_proposal(
        json.dumps(proposal, ensure_ascii=False),
        trusted_evidence_ids=("snapshot:1",),
    )
    assert result.thesis == proposal["thesis"]
    assert result.risks == proposal["risks"]


def test_readable_international_evidence_id_remains_exact_match():
    identifier = "filing:échantillon"
    proposal = {**BASE, "evidence_ids": [identifier]}
    result = parse_research_ai_proposal(
        json.dumps(proposal, ensure_ascii=False),
        trusted_evidence_ids=(identifier,),
    )
    assert result.evidence_ids == (identifier,)
