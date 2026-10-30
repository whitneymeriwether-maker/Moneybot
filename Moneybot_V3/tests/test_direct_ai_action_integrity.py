"""Direct paper entry must reject non-schema AI actions without rendering them."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from v3_decision import (
    AIProposal, Candidate, PaperAccount, validate_paper_entry,
)


class SpoofBuy:
    """An untrusted action object must not impersonate the BUY string."""

    def __eq__(self, other):
        return other == "BUY"

    def __str__(self):
        raise AssertionError("Untrusted action must not enter an audit reason")


class BuySubclass(str):
    pass


def entry(action):
    candidate = Candidate(
        "SPY", datetime.now(timezone.utc), 100.0,
        True, True, 2.0, True, 1.0, 0,
    )
    proposal = AIProposal(
        action, "Hypothetical observed breakout", "Reversal and liquidity",
        ("research:bar-1",), 0.7,
    )
    account = PaperAccount(1000, 1000, 0, 0)
    return validate_paper_entry(candidate, proposal, account)


@pytest.mark.parametrize("bad_action", [
    None, True, 1, b"BUY", "", "SELL", "buy", " BUY",
    SpoofBuy(), BuySubclass("BUY"),
])
def test_direct_proposal_rejects_invalid_action_without_echo(bad_action):
    result = entry(bad_action)
    assert not result.approved
    assert result.reason == "Invalid AI proposal action"


@pytest.mark.parametrize("action", ["WAIT", "REJECT"])
def test_supported_nonbuy_actions_still_return_normal_denial(action):
    result = entry(action)
    assert not result.approved
    assert result.reason == f"AI decision: {action}"


def test_supported_buy_still_reaches_paper_advisory():
    result = entry("BUY")
    assert result.approved
    assert result.quantity == 5
