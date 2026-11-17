"""Authenticated research quote -> audited paper BUY preview; never a fill.

This seam is deliberately synchronous and read-only. A future autonomous
executor needs a separate, durable execution-time gate and scheduler.
"""
from .alpaca_market_data import latest_alpaca_quote
from .paper_execution_preview import preview_paper_buy
from .paper_risk_preflight import PaperRiskRejected


def preview_alpaca_paper_buy(*, ledger, symbol, quantity,
                             max_order_notional, max_position_notional,
                             paper_only, kill_switch, now=None,
                             key_id=None, secret_key=None, opener=None):
    """Fetch a fresh authenticated IEX quote and evaluate local audited cash.

    Credentials never appear in results. Provider midpoint is a research
    reference, not an executable fill price or broker-confirmed execution.
    """
    if paper_only is not True or kill_switch is not False:
        raise PaperRiskRejected("paper execution disabled")
    try:
        observation = latest_alpaca_quote(
            symbol, key_id=key_id, secret_key=secret_key,
            now=now, opener=opener)
        if (observation.get("provider") != "alpaca"
                or observation.get("feed") != "iex"
                or observation.get("price_type") != "bid_ask_midpoint_not_execution"
                or observation.get("execution_authorized") is not False):
            raise ValueError("unexpected authenticated quote contract")
        quote = {
            "symbol": observation["symbol"],
            "price": observation["price"],
            "timestamp_utc": observation["timestamp_utc"],
            "provider": "alpaca",
            "authenticated_transport": True,
            "provider_verified": True,
        }
        result = preview_paper_buy(
            ledger=ledger, quote=quote, symbol=symbol, quantity=quantity,
            max_order_notional=max_order_notional,
            max_position_notional=max_position_notional,
            paper_only=True, kill_switch=False, now=now)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise PaperRiskRejected("authenticated paper preview unavailable") from exc
    return {
        **result,
        "feed": "iex",
        "reference_price_type": "bid_ask_midpoint_not_execution",
        "execution_authorized": False,
        "ledger_mutated": False,
    }
