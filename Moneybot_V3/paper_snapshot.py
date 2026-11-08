"""Conservative read-only projection of isolated paper-journal events.

Not an execution engine. Fill observations are never treated as verified fills.
"""
from decimal import Decimal

from paper_journal import PaperJournal, _amount


def paper_cash_snapshot(path):
    """Project recorded cash movements; fail closed on unknown/unverified events.

    This is a journal-derived accounting view, NOT a brokerage balance or P&L.
    """
    events = PaperJournal(path).events()
    cash = Decimal("0")
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    for event in events:
        amount = Decimal(_amount(event["amount"]))
        kind = event["event_type"]
        if kind == "paper_deposit":
            deposits += amount
            cash += amount
        elif kind == "paper_withdrawal":
            if amount > cash:
                raise ValueError("Paper cash journal contains an overdraft")
            withdrawals += amount
            cash -= amount
        else:
            raise ValueError("Cannot project unverified fill or unknown journal event")
    # Dashboard cash is cent-denominated; never silently round sub-cent events.
    if any(value != value.quantize(Decimal("0.01")) for value in (cash, deposits, withdrawals)):
        raise ValueError("Journal contains sub-cent amounts unsupported by dashboard")
    return {
        "source": "isolated_paper_journal",
        "verification": "journal_only_not_broker_or_market_verified",
        "trading_ready": False,
        "cash": format(cash, ".2f"),
        "deposits": format(deposits, ".2f"),
        "withdrawals": format(withdrawals, ".2f"),
        "event_count": len(events),
        "paper_trades": None,
        "performance": None,
    }
