"""Pure, fail-closed V3 paper-trade decision gate.

This module NEVER places or records an order. Its result is advisory only;
an eventual execution worker must recheck these constraints under the same
ledger write transaction and independently authenticate market observations.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from verified_market_quote import verified_quote


def paper_decision(*, quote, provider, authenticated, symbol, now, account,
                   side, quantity, max_order_dollars="100.00",
                   max_position_dollars="250.00", max_daily_loss_dollars="25.00",
                   daily_realized_pnl="0.00", market_open=False):
    """Validate a single whole-share long-only hypothetical order.

    Returns a non-executable candidate, never an order or permission to fill.
    The caller must pass a fresh audited account snapshot and daily realized
    P&L from an independently audited ledger; missing evidence fails closed.
    """
    if market_open is not True:
        raise ValueError("Market session not verified open")
    q = verified_quote(quote, provider=provider, authenticated=authenticated,
                       expected_symbol=symbol, now=now)
    if side not in ("BUY", "SELL") or type(side) is not str:
        raise ValueError("Invalid paper side")
    if type(quantity) is not int or not 0 < quantity <= 100000:
        raise ValueError("Invalid whole-share quantity")
    if type(account) is not dict or set(account) != {"cash", "positions", "fill_count"}:
        raise ValueError("Missing audited paper account state")
    if type(account["fill_count"]) is not int or account["fill_count"] < 0:
        raise ValueError("Invalid paper fill count")
    if type(account["positions"]) is not dict:
        raise ValueError("Invalid paper positions")
    def money(v, *, allow_negative=False):
        if type(v) not in (str, Decimal):
            raise ValueError("Money must be exact decimal")
        try:
            d = Decimal(v)
            if not d.is_finite() or abs(d) > Decimal("1000000000") or d != d.quantize(Decimal(".01")) or (d < 0 and not allow_negative):
                raise ValueError("Invalid money amount")
            return d
        except (InvalidOperation, OverflowError):
            raise ValueError("Invalid money amount") from None
    cash = money(account["cash"])
    order_limit = money(max_order_dollars)
    position_limit = money(max_position_dollars)
    loss_limit = money(max_daily_loss_dollars)
    realized = money(daily_realized_pnl, allow_negative=True)
    if min(order_limit, position_limit, loss_limit) <= 0:
        raise ValueError("Risk limits must be positive")
    if realized <= -loss_limit:
        raise ValueError("Daily realized paper loss limit reached")
    price = money(q["price"])
    notional = price * quantity
    if notional > order_limit:
        raise ValueError("Paper order notional limit exceeded")
    position = account["positions"].get(symbol, {"quantity": 0, "cost_basis": "0.00"})
    if type(position) is not dict or set(position) != {"quantity", "cost_basis"}:
        raise ValueError("Invalid position state")
    held = position["quantity"]
    if type(held) is not int or held < 0:
        raise ValueError("Invalid held quantity")
    basis = money(position["cost_basis"])
    if (held == 0) != (basis == 0):
        raise ValueError("Inconsistent position basis")
    if side == "BUY":
        if notional > cash:
            raise ValueError("Insufficient paper cash")
        if (held + quantity) * price > position_limit:
            raise ValueError("Paper position exposure limit exceeded")
    elif quantity > held:
        raise ValueError("Cannot sell unowned paper shares")
    return {"symbol": symbol, "side": side, "quantity": quantity,
            "reference_price": q["price"], "reference_timestamp_utc": q["timestamp_utc"],
            "estimated_notional": str(notional.quantize(Decimal(".01"))),
            "candidate_only": True, "execution_authorized": False,
            "requires_atomic_execution_recheck": True}
