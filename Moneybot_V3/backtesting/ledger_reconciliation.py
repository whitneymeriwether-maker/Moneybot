"""Independent, offline reconciliation of closed simulator trades to SQLite paper fills.

This is a diagnostic bridge, not a fill engine. It only accepts exact-cent
simulated prices and fees, and creates a disposable local ledger. It never
writes to an existing account, contacts a provider, or submits orders.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from paper_ledger import PaperLedger, _cents, _SYMBOL
from backtesting.trade_simulator import SimulatedTrade


_CENT = Decimal("0.01")


def _exact_cent(value, *, positive):
    """Fail closed rather than silently rounding fractional-cent paper fills."""
    if type(value) not in (int, float):
        raise ValueError("Simulated prices and fees must be finite numbers")
    try:
        if not isfinite(value):
            raise ValueError("Non-finite simulated fill")
        amount = Decimal(str(value))
        if (amount < 0 or (positive and amount == 0)
                or amount != amount.quantize(_CENT)):
            raise ValueError("Simulated fill is negative or not exact cents")
        return format(amount, ".2f")
    except (OverflowError, InvalidOperation):
        raise ValueError("Invalid simulated fill amount") from None


def _instant(value):
    if (not isinstance(value, datetime)
            or value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("Simulated fill timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def reconcile_closed_simulation(trades, *, symbol, starting_cash="1000.00"):
    """Reconcile non-overlapping, fully closed, cent-exact hypothetical trades.

    All records are validated before a disposable ledger is opened. The
    replay applies each BUY/SELL pair chronologically, runs the ledger's
    independent history audit, and compares its exact-cent realized PnL and
    ending cash to Decimal arithmetic on the supplied trades. No market
    prices, fill provenance, or simulator execution assumptions are verified.
    """
    if type(trades) not in (list, tuple):
        raise ValueError("Completed simulated trades must be a list or tuple")
    # Let the same ledger constraints validate ticker identity and capital.
    if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("Invalid simulated trade symbol")
    initial = Decimal(_cents(starting_cash)) / 100
    validated = []
    expected_pnl = Decimal("0.00")
    previous_exit = None

    for trade in trades:
        if not isinstance(trade, SimulatedTrade):
            raise ValueError("Invalid simulated trade record")
        entry_at = _instant(trade.entry_time)
        exit_at = _instant(trade.exit_time)
        # OHLC stop/target exits can occur after the opening fill within
        # the same minute. Minute bars cannot resolve their subminute order,
        # but the simulator records BUY before SELL and the paper ledger
        # preserves that insertion order when timestamps tie.
        if exit_at < entry_at:
            raise ValueError("Simulated trade exit cannot precede entry")
        if previous_exit is not None and entry_at < previous_exit:
            raise ValueError("Simulated trades must not overlap or be reordered")
        previous_exit = exit_at
        if type(trade.quantity) is not int or trade.quantity <= 0:
            raise ValueError("Invalid simulated trade quantity")

        entry = _exact_cent(trade.entry_price, positive=True)
        exit_price = _exact_cent(trade.exit_price, positive=True)
        entry_fee = _exact_cent(trade.entry_fee, positive=False)
        exit_fee = _exact_cent(trade.exit_fee, positive=False)
        qty = trade.quantity
        expected_pnl += (
            (Decimal(exit_price) - Decimal(entry)) * qty
            - Decimal(entry_fee) - Decimal(exit_fee)
        )
        validated.append((
            entry_at, exit_at, qty, entry, exit_price, entry_fee, exit_fee
        ))

    with TemporaryDirectory(prefix="moneybot-v3-reconcile-") as tmp:
        ledger = PaperLedger(Path(tmp) / "paper.sqlite3", starting_cash=starting_cash)
        for index, (entry_at, exit_at, qty, entry, exit_price, entry_fee, exit_fee) in enumerate(validated):
            ledger.record_fill(
                event_id=f"reconcile-{index}-buy", timestamp=entry_at,
                symbol=symbol, side="BUY", quantity=qty,
                price=entry, fee=entry_fee,
            )
            ledger.record_fill(
                event_id=f"reconcile-{index}-sell", timestamp=exit_at,
                symbol=symbol, side="SELL", quantity=qty,
                price=exit_price, fee=exit_fee,
            )
        audited = ledger.audit_history()
        snapshot = ledger.snapshot()
        if (snapshot["positions"] != {}
                or snapshot["fill_count"] != 2 * len(validated)
                or audited["audited_fills"] != 2 * len(validated)
                or Decimal(snapshot["cash"]) != initial + expected_pnl
                or Decimal(snapshot["realized_pnl"]) != expected_pnl
                or audited["cash"] != snapshot["cash"]
                or audited["realized_pnl"] != snapshot["realized_pnl"]):
            raise ValueError("Simulated trades disagree with audited paper ledger")

    return {
        "trade_count": len(validated),
        "audited_fills": audited["audited_fills"],
        "starting_cash": format(initial, ".2f"),
        "ending_cash": snapshot["cash"],
        "net_pnl": snapshot["realized_pnl"],
    }
