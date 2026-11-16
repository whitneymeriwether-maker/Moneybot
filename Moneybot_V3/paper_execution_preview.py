"""Read-only bridge from audited local paper accounting to quote risk preflight.

This is an advisory preview, never an execution gate. In particular, a later
executor MUST re-read balances and enforce limits within its write transaction.
No broker API, order submission, or ledger mutation exists here.
"""
from decimal import Decimal
from .market_data_boundary import verified_quote
from .paper_risk_preflight import check_paper_buy, PaperRiskRejected


def preview_paper_buy(*, ledger, quote, symbol, quantity,
                      max_order_notional, max_position_notional,
                      paper_only, kill_switch, now=None):
    """Return a non-executable proposal using actual audited local cash/holdings."""
    if paper_only is not True or kill_switch is not False:
        raise PaperRiskRejected("paper execution disabled")
    try:
        observation = verified_quote(quote, expected_symbol=symbol, now=now)
        # Audit history first; a reconciled balance alone cannot prove fills.
        audit = ledger.audit_history()
        snapshot = ledger.snapshot()
        if (audit["audited_fills"] != snapshot["fill_count"]
                or audit["cash"] != snapshot["cash"]
                or audit["realized_pnl"] != snapshot["realized_pnl"]):
            raise ValueError("paper ledger audit mismatch")
        holding = snapshot["positions"].get(symbol, {})
        held = holding.get("quantity", 0)
        if type(held) is not int or held < 0:
            raise ValueError("invalid paper holdings")
        existing_notional = observation["price"] * Decimal(held)
        result = check_paper_buy(
            quote=quote, symbol=symbol, quantity=quantity,
            available_cash=snapshot["cash"],
            max_order_notional=max_order_notional,
            max_position_notional=max_position_notional,
            existing_position_notional=str(existing_notional),
            paper_only=paper_only, kill_switch=kill_switch, now=now,
        )
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise PaperRiskRejected("unavailable or unverified paper preview") from exc
    return {**result, "account_source": "audited_local_hypothetical_ledger",
            "execution_authorized": False, "ledger_mutated": False}
