"""Strict, offline boundary for externally generated V3 research AI proposals.

No model, network, database, or brokerage integration. Evidence identifiers
must come from an independently supplied allowlist, never from model claims.
Passing this parser does NOT establish evidence authenticity or trading merit.
"""

import json
from math import isfinite

from v3_decision import AIProposal


_MAX_JSON_BYTES = 16384
_MAX_REASON_CHARS = 2000
_MAX_EVIDENCE_IDS = 16
_MAX_EVIDENCE_ID_CHARS = 128
_REQUIRED_FIELDS = frozenset({
    "action", "thesis", "risks", "evidence_ids", "confidence",
})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate AI proposal JSON field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite AI proposal JSON number")


def _valid_evidence_id(value):
    return (
        type(value) is str
        and 0 < len(value) <= _MAX_EVIDENCE_ID_CHARS
        and value == value.strip()
        and all(ord(char) >= 32 for char in value)
    )


def _valid_reason(value):
    return (
        type(value) is str
        and 0 < len(value) <= _MAX_REASON_CHARS
        and bool(value.strip())
        and all(ord(char) >= 32 for char in value)
    )


def parse_research_ai_proposal(payload, *, trusted_evidence_ids):
    """Parse a bounded JSON proposal, binding citations to trusted input IDs.

    The trusted IDs must be supplied by the caller from a separately
    verified research snapshot. Model-supplied citations are references,
    never evidence themselves. BUY requires at least one trusted reference.
    WAIT and REJECT may have no references but must still explain themselves.
    """
    if (
        type(trusted_evidence_ids) is not tuple
        or len(trusted_evidence_ids) > 128
        or any(not _valid_evidence_id(item) for item in trusted_evidence_ids)
        or len(set(trusted_evidence_ids)) != len(trusted_evidence_ids)
    ):
        raise ValueError("Invalid trusted evidence identifier allowlist")
    if type(payload) is not str:
        raise ValueError("AI proposal must be JSON text")
    try:
        size = len(payload.encode("utf-8"))
    except UnicodeError:
        raise ValueError("Invalid AI proposal text encoding") from None
    if size == 0 or size > _MAX_JSON_BYTES:
        raise ValueError("AI proposal JSON exceeds size bounds")
    try:
        proposal = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        raise ValueError("Invalid AI proposal JSON") from None
    if type(proposal) is not dict or proposal.keys() != _REQUIRED_FIELDS:
        raise ValueError("AI proposal requires exactly the defined fields")
    action = proposal["action"]
    if type(action) is not str or action not in ("BUY", "WAIT", "REJECT"):
        raise ValueError("Invalid AI proposal action")
    if not _valid_reason(proposal["thesis"]) or not _valid_reason(proposal["risks"]):
        raise ValueError("AI proposal requires bounded auditable reasoning")
    confidence = proposal["confidence"]
    try:
        valid_confidence = (
            type(confidence) in (int, float)
            and isfinite(confidence)
            and 0 <= confidence <= 1
        )
    except (OverflowError, ValueError):
        valid_confidence = False
    if not valid_confidence:
        raise ValueError("Invalid AI proposal confidence")
    evidence = proposal["evidence_ids"]
    if (
        type(evidence) is not list
        or len(evidence) > _MAX_EVIDENCE_IDS
        or any(not _valid_evidence_id(item) for item in evidence)
        or len(set(evidence)) != len(evidence)
        or (action == "BUY" and not evidence)
        or not set(evidence).issubset(trusted_evidence_ids)
    ):
        raise ValueError("AI proposal cites missing or invalid trusted evidence")
    return AIProposal(
        action=action,
        thesis=proposal["thesis"],
        risks=proposal["risks"],
        evidence_ids=tuple(evidence),
        confidence=float(confidence),
    )
