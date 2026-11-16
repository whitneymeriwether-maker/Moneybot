"""Fail-closed preflight for hypothetical PAPER-ONLY buy proposals.

Pure decision function. Never submits orders or records fills. A future executor
MUST recheck these limits inside its durable accounting transaction.
"""
from decimal import Decimal, InvalidOperation, DecimalException
from .market_data_boundary import verified_quote


class PaperRiskRejected(ValueError):
    pass


def _decimal(value, label, *, allow_zero=False):
    if type(value) is not str:
        raise PaperRiskRejected(label + " must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise PaperRiskRejected("invalid " + label) from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise PaperRiskRejected("invalid " + label)
    if number.as_tuple().exponent < -6:
        raise PaperRiskRejected("excessive precision: " + label)
    # Reject oversized scientific notation before arithmetic or string formatting.
    # This preflight is advisory, not an execution authorization.
    if number.adjusted() > 12:
        raise PaperRiskRejected("out-of-bounds " + label)
    return number


def check_paper_buy(*, quote, symbol, quantity, available_cash,
                    max_order_notional, max_position_notional,
                    existing_position_notional, paper_only, kill_switch,
                    now=None):
    """Return an approved proposal, NOT a fill or permission to trade live.

    All values must be supplied from trustworthy, current sources. Caller must
    not infer a fill from the quote midpoint. Reject unknown account state.
    """
    if paper_only is not True or kill_switch is not False:
        raise PaperRiskRejected("paper-only authorization or kill switch invalid")
    try:
        observation = verified_quote(quote, expected_symbol=symbol, now=now)
    except (ValueError, TypeError) as exc:
        raise PaperRiskRejected("unverified market quote") from exc
    qty = _decimal(quantity, "quantity")
    # The durable ledger supports whole shares only. Reject fractional
    # proposals here rather than approving an unexecutable quantity.
    if qty != qty.to_integral_value():
        raise PaperRiskRejected("paper quantity must be whole shares")
    cash = _decimal(available_cash, "cash", allow_zero=True)
    order_limit = _decimal(max_order_notional, "order limit")
    position_limit = _decimal(max_position_notional, "position limit")
    position = _decimal(existing_position_notional, "position", allow_zero=True)
    try:
        notional = observation["price"] * qty
    except DecimalException as exc:
        raise PaperRiskRejected("unrepresentable paper notional") from exc
    if notional > cash:
        raise PaperRiskRejected("insufficient paper cash")
    if notional > order_limit:
        raise PaperRiskRejected("paper order limit exceeded")
    if position + notional > position_limit:
        raise PaperRiskRejected("paper position limit exceeded")
    return {
        "status": "preflight_only_not_executed",
        "symbol": symbol,
        "quantity": str(qty),
        "reference_price": str(observation["price"]),
        "reference_notional": str(notional),
        "quote_provider": observation["provider"],
        "quote_observed_at": observation["observed_at"].isoformat(),
    }
