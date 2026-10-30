"""Offline V3 research review: JSON AI proposal -> paper-only advisory.

This bridge performs no I/O, model calls, ledger writes, or broker operations.
The trusted evidence allowlist must be independently assembled by the caller;
a successful review is NOT evidence authentication or permission to trade.
"""

from dataclasses import dataclass

from v3_decision import (
    AIProposal, Candidate, Decision, PaperAccount, RiskPolicy,
    validate_paper_entry,
)
from v3_proposal_adapter import parse_research_ai_proposal


@dataclass(frozen=True)
class ResearchReview:
    """Parsed research proposal and non-executing paper entry advisory."""

    proposal: AIProposal | None
    decision: Decision


def review_research_proposal(
    payload: str,
    *,
    trusted_evidence_ids: tuple[str, ...],
    candidate: Candidate,
    account: PaperAccount,
    policy: RiskPolicy = RiskPolicy(),
) -> ResearchReview:
    """Validate untrusted JSON before running the independent paper risk gate.

    Invalid JSON, malformed schema, or untrusted evidence fail closed with a
    fixed audit reason; the untrusted payload is never reflected in a denial.
    Valid WAIT/REJECT proposals are preserved for research audit but cannot
    approve an entry. Even an approved BUY is an advisory, not a fill.
    """
    try:
        proposal = parse_research_ai_proposal(
            payload, trusted_evidence_ids=trusted_evidence_ids,
        )
    except ValueError:
        return ResearchReview(
            None, Decision(False, "Invalid research AI proposal or evidence"),
        )
    return ResearchReview(
        proposal, validate_paper_entry(candidate, proposal, account, policy),
    )
