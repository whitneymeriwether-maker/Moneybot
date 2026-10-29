"""The advisory gate must respect local ledger hard limits without placing orders."""
from dataclasses import replace
from datetime import datetime, timezone

from paper_ledger import MAX_CENTS, MAX_SHARES
from v3_decision import (
    AIProposal, Candidate, PaperAccount, RiskPolicy, validate_paper_entry,
)


def _decision(*, price, atr, equity, policy=None):
    candidate = Candidate(
        "AMD", datetime.now(timezone.utc), price, True, True, 2.0,
        True, atr, 0,
    )
    proposal = AIProposal(
        "BUY", "Documented hypothetical breakout", "Gap risk",
        ("offline:1",), 0.7,
    )
    account = PaperAccount(
        cash=equity, equity=equity, current_exposure=0,
        realized_pnl_today=0, starting_equity=equity, peak_equity=equity,
    )
    return validate_paper_entry(
        candidate, proposal, account,
        policy or RiskPolicy(risk_per_trade=1.0),
    )


def test_rejects_more_shares_than_paper_ledger_can_record():
    result = _decision(price=1.0, atr=0.01, equity=2 * (MAX_SHARES + 1))
    assert not result.approved
    assert result.reason == "Paper sizing exceeds ledger bounds"


def test_accepts_maximum_ledger_share_count():
    result = _decision(price=1.0, atr=0.01, equity=2 * MAX_SHARES)
    assert result.approved
    assert result.quantity == MAX_SHARES


def test_rejects_notional_above_ledger_accounting_limit():
    result = _decision(price=2e12, atr=1e12, equity=1e14)
    assert not result.approved
    assert result.reason == "Paper sizing exceeds ledger bounds"


def test_accepts_notional_at_ledger_limit():
    limit_dollars = MAX_CENTS / 100
    result = _decision(
        price=limit_dollars, atr=limit_dollars / 2,
        equity=limit_dollars,
        policy=RiskPolicy(risk_per_trade=1.0, max_exposure=1.0),
    )
    assert result.approved
    assert result.quantity == 1
