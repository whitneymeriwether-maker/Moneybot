"""The advisory gate must respect local ledger hard limits without placing orders."""
from dataclasses import replace

import pytest
from datetime import datetime, timezone

from paper_ledger import MAX_CENTS, MAX_SHARES
from v3_decision import (
    AIProposal, Candidate, PaperAccount, RiskPolicy, validate_paper_entry,
)


def _decision(*, price, atr, equity, policy=None, account_updates=None):
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
    if account_updates:
        account = replace(account, **account_updates)
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


@pytest.mark.parametrize("price", [0.015, 0.001, 0.0100001, 1.234])
def test_rejects_subcent_prices_that_paper_ledger_cannot_record(price):
    result = _decision(price=price, atr=price / 4, equity=1000)
    assert not result.approved
    assert result.reason == "Paper price is not representable in ledger cents"


@pytest.mark.parametrize("price", [0.01, 0.29, 1.25, 100.0])
def test_accepts_exact_cent_prices_without_binary_float_false_positives(price):
    result = _decision(price=price, atr=price / 4, equity=1000)
    assert result.approved
    assert result.quantity > 0


@pytest.mark.parametrize("field,value", [
    ("cash", 1000.001),
    ("cash", MAX_CENTS / 100 + 0.01),
    ("starting_equity", 1000.001),
    ("starting_equity", MAX_CENTS / 100 + 0.01),
    ("realized_pnl_today", 0.001),
    ("realized_pnl_today", -0.001),
])
def test_entry_rejects_paper_account_values_not_recordable_in_ledger(field, value):
    result = _decision(
        price=100.0, atr=1.0, equity=1000.0,
        account_updates={field: value},
    )
    assert not result.approved
    assert result.reason == "Paper account monetary state incompatible with ledger"


@pytest.mark.parametrize("field,value", [
    ("cash", 1000.001),
    ("cash", MAX_CENTS / 100 + 0.01),
    ("starting_equity", 1000.001),
    ("starting_equity", MAX_CENTS / 100 + 0.01),
    ("realized_pnl_today", 0.001),
    ("realized_pnl_today", -0.001),
])
def test_overnight_rejects_paper_account_values_not_recordable_in_ledger(field, value):
    from v3_decision import validate_overnight_hold

    account = PaperAccount(
        cash=1000.0, equity=1000.0, current_exposure=200.0,
        realized_pnl_today=0.0, starting_equity=1000.0, peak_equity=1000.0,
    )
    account = replace(account, **{field: value})
    result = validate_overnight_hold(
        1, 100.0, account, "Hypothetical overnight thesis", ("offline:1",),
    )
    assert not result.approved
    assert result.reason == "Paper account monetary state incompatible with ledger"


def test_advisory_accepts_cent_accounting_with_subcent_marked_equity():
    from v3_decision import validate_overnight_hold

    account = PaperAccount(
        cash=999.99, equity=1000.005, current_exposure=200.005,
        realized_pnl_today=-0.01, starting_equity=1000.0,
        peak_equity=1000.005,
    )
    result = validate_overnight_hold(
        1, 100.005, account, "Hypothetical overnight thesis", ("offline:1",),
    )
    assert result.approved
    entry = _decision(
        price=100.0, atr=1.0, equity=1000.005,
        account_updates={
            "cash": 999.99, "starting_equity": 1000.0,
            "realized_pnl_today": -0.01,
        },
    )
    assert entry.approved
