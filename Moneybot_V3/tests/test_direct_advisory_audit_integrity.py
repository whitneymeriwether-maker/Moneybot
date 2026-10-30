"""Direct callers must not bypass AI proposal audit-text constraints."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from v3_decision import (
    AIProposal, Candidate, PaperAccount, validate_overnight_hold,
    validate_paper_entry,
)


CANDIDATE = Candidate(
    "SPY", datetime.now(timezone.utc), 100.0, True, True, 2.0,
    True, 1.0, 0,
)
PROPOSAL = AIProposal(
    "BUY", "Observed hypothetical breakout", "Reversal risk",
    ("minute:SPY:1",), 0.7,
)
ACCOUNT = PaperAccount(1000, 1000, 200, 0)


@pytest.mark.parametrize("field,bad", [
    ("thesis", "Visible\u202ehidden"),
    ("risks", "Hidden\u200btext"),
    ("thesis", "x" * 2001),
    ("risks", "x" * 2001),
    ("thesis", "\ud800"),
    ("risks", "Only\nline break"),
    ("thesis", "  "),
])
def test_direct_entry_rejects_non_auditable_reasoning(field, bad):
    proposal = replace(PROPOSAL, **{field: bad})
    result = validate_paper_entry(CANDIDATE, proposal, ACCOUNT)
    assert not result.approved
    assert result.reason == "Missing auditable reasoning or evidence"


@pytest.mark.parametrize("ids", [
    ("minute:SPY:1", "minute:SPY:1"),
    ("minute:\u202eSPY",),
    ("minute:\u200bSPY",),
    (" minute:SPY:1",),
    ("minute:SPY:1 ",),
    ("x" * 129,),
    tuple(f"source:{i}" for i in range(17)),
    ("source:\ud800",),
])
def test_direct_entry_and_overnight_hold_reject_unreliable_evidence(ids):
    entry = validate_paper_entry(
        CANDIDATE, replace(PROPOSAL, evidence_ids=ids), ACCOUNT,
    )
    hold = validate_overnight_hold(
        1, 200, ACCOUNT, "Documented hold thesis", ids,
    )
    assert not entry.approved
    assert entry.reason == "Missing auditable reasoning or evidence"
    assert not hold.approved
    assert hold.reason == "Overnight thesis and evidence required"


@pytest.mark.parametrize("bad", [
    "Thesis\u202eoverride", "Thesis\u200bhidden", "x" * 2001,
    "New\nline", "\ud800", "  ",
])
def test_direct_overnight_hold_rejects_non_auditable_thesis(bad):
    result = validate_overnight_hold(
        1, 200, ACCOUNT, bad, ("minute:SPY:1",),
    )
    assert not result.approved
    assert result.reason == "Overnight thesis and evidence required"


def test_readable_multilingual_direct_advisories_remain_valid():
    proposal = replace(
        PROPOSAL, thesis="Étude du marché 市场观察",
        risks="Risque de liquidité 风险", evidence_ids=("étude:市场",),
    )
    entry = validate_paper_entry(CANDIDATE, proposal, ACCOUNT)
    hold = validate_overnight_hold(
        1, 200, ACCOUNT, "Risque étudié 市场观察", ("étude:市场",),
    )
    assert entry.approved
    assert hold.approved
