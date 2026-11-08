"""Conservative read-only projection of isolated paper-journal events.

Not an execution engine. Fill observations are never treated as verified fills.
"""
from decimal import Decimal
from datetime import datetime, timezone

from paper_journal import PaperJournal, _amount


def paper_cash_snapshot(path):
    """Project recorded cash movements; fail closed on unknown/unverified events.

    This is a journal-derived accounting view, NOT a brokerage balance or P&L.
    """
    events = PaperJournal(path).events()
    cash = Decimal("0")
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    last_recorded_at = None
    for event in events:
        # A journal timestamp is an observation time, not a market-data timestamp.
        timestamp = event["recorded_at"]
        if not isinstance(timestamp, str):
            raise ValueError("Invalid journal timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ValueError("Invalid journal timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Journal timestamp must include timezone")
        last_recorded_at = parsed.astimezone(timezone.utc).isoformat()
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
        "last_recorded_at": last_recorded_at,
        "paper_trades": None,
        "performance": None,
    }
