"""Durable, broker-disconnected cash ledger for Moneybot V3 paper research.

This is a local SQLite prototype, NOT a Neon adapter or order execution
service. Only externally supplied hypothetical fills can change its balance.
Amounts are exact cents, quantities are whole shares, and transactions are
atomic. A real paper broker integration must independently verify fills,
market timestamps, risk gates, and execution semantics before calling this.
"""

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


MAX_CENTS = 10**14  # Reject SQLite integer overflow and implausible balances.
MAX_SHARES = 10**7
_CENT = Decimal("0.01")
_EVENT_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def _cents(value, *, allow_zero=False):
    """Require exact, finite decimal-dollar input; never accept binary floats."""
    if type(value) not in (str, Decimal):
        raise ValueError("Money must be a decimal string or Decimal")
    try:
        amount = Decimal(value)
        if (
            not amount.is_finite()
            or amount < 0
            or (not allow_zero and amount == 0)
            or amount > Decimal(MAX_CENTS) / 100
            or amount != amount.quantize(_CENT)
        ):
            raise ValueError("Invalid money amount")
        return int(amount * 100)
    except (InvalidOperation, TypeError, OverflowError):
        raise ValueError("Invalid money amount") from None


def _money(cents):
    return str((Decimal(cents) / 100).quantize(_CENT))


class PaperLedger:
    """One persistent, long-only, cash-funded *hypothetical* paper account.

    Each fill requires a unique event ID. Exact retries are harmless; a
    conflicting reuse of the same ID is rejected. Fills cannot be backdated
    relative to an already recorded fill. No broker or network APIs exist.
    """

    def __init__(self, db_path, starting_cash="1000.00"):
        if not isinstance(db_path, (str, Path)) or not str(db_path).strip():
            raise ValueError("A persistent SQLite file path is required")
        self.db_path = str(db_path)
        if self.db_path == ":memory:":
            raise ValueError("In-memory databases are not persistent")
        initial = _cents(starting_cash)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """CREATE TABLE IF NOT EXISTS paper_account (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        starting_cash_cents INTEGER NOT NULL,
                        cash_cents INTEGER NOT NULL,
                        realized_pnl_cents INTEGER NOT NULL
                    )"""
                )
                db.execute(
                    """CREATE TABLE IF NOT EXISTS paper_positions (
                        symbol TEXT PRIMARY KEY,
                        quantity INTEGER NOT NULL CHECK (quantity > 0),
                        cost_basis_cents INTEGER NOT NULL CHECK (cost_basis_cents >= 0)
                    )"""
                )
                db.execute(
                    """CREATE TABLE IF NOT EXISTS paper_fills (
                        event_id TEXT PRIMARY KEY,
                        timestamp_utc TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity INTEGER NOT NULL,
                        price_cents INTEGER NOT NULL,
                        fee_cents INTEGER NOT NULL
                    )"""
                )
                row = db.execute(
                    "SELECT starting_cash_cents FROM paper_account WHERE id=1"
                ).fetchone()
                if row is None:
                    db.execute(
                        """INSERT INTO paper_account
                        (id, starting_cash_cents, cash_cents, realized_pnl_cents)
                        VALUES (1, ?, ?, 0)""",
                        (initial, initial),
                    )
                elif row[0] != initial:
                    raise ValueError("Existing paper account has different starting cash")
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _assert_consistent(db):
        """Fail closed if persisted cash, positions, and PnL do not reconcile.

        For average-cost cash accounting, cash + remaining acquisition
        basis - realized PnL must always equal initial cash. This detects
        many accidental/manual state edits, but is not a cryptographic
        audit of the fill history or protection from coordinated tampering.
        Must run inside the caller's SQLite transaction.
        """
        row = db.execute(
            """SELECT starting_cash_cents, cash_cents, realized_pnl_cents
               FROM paper_account WHERE id=1"""
        ).fetchone()
        if row is None:
            raise ValueError("Corrupt paper account: missing account row")
        start, cash, realized = row
        if (
            type(start) is not int or not 0 < start <= MAX_CENTS
            or type(cash) is not int or not 0 <= cash <= MAX_CENTS
            or type(realized) is not int or abs(realized) > MAX_CENTS
        ):
            raise ValueError("Corrupt paper account balances")
        total_basis = 0
        for quantity, basis in db.execute(
            "SELECT quantity, cost_basis_cents FROM paper_positions"
        ):
            if (
                type(quantity) is not int or not 0 < quantity <= MAX_SHARES
                or type(basis) is not int or not 0 <= basis <= MAX_CENTS
            ):
                raise ValueError("Corrupt paper position")
            total_basis += basis
            if total_basis > MAX_CENTS:
                raise ValueError("Corrupt paper position basis")
        if cash + total_basis - realized != start:
            raise ValueError("Corrupt paper account accounting invariant")

    def record_fill(
        self, *, event_id, timestamp, symbol, side, quantity, price,
        fee="0.00",
    ):
        """Atomically record a hypothetical fill; True=new, False=exact retry.

        BUY reserves cash including fees. SELL requires owned shares, releases
        rounded average-cost basis, and realizes proceeds less fees and basis.
        Fees are included in the acquisition basis for a BUY. No shorting,
        margin, partial order execution, or external order submission.
        """
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid paper fill event ID")
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            raise ValueError("Paper fill timestamp must be timezone-aware")
        utc_time = timestamp.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        )
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ValueError("Invalid paper symbol")
        if side not in ("BUY", "SELL") or type(side) is not str:
            raise ValueError("Paper side must be BUY or SELL")
        if type(quantity) is not int or not 0 < quantity <= MAX_SHARES:
            raise ValueError("Invalid whole-share paper quantity")

        price_cents = _cents(price)
        fee_cents = _cents(fee, allow_zero=True)
        gross = price_cents * quantity
        if gross > MAX_CENTS or gross + fee_cents > MAX_CENTS:
            raise ValueError("Paper fill exceeds accounting bounds")
        payload = (
            utc_time, symbol, side, quantity, price_cents, fee_cents
        )

        with closing(self._connect()) as db:
            try:
                # SQLite writer lock serializes independent workers before
                # checking the event ID or the available paper cash.
                db.execute("BEGIN IMMEDIATE")
                self._assert_consistent(db)
                existing = db.execute(
                    """SELECT timestamp_utc, symbol, side, quantity,
                              price_cents, fee_cents
                       FROM paper_fills WHERE event_id=?""",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    if existing != payload:
                        raise ValueError("Conflicting paper fill event ID")
                    db.commit()
                    return False

                last = db.execute(
                    "SELECT MAX(timestamp_utc) FROM paper_fills"
                ).fetchone()[0]
                if last is not None and utc_time < last:
                    raise ValueError("Backdated paper fill")

                cash, realized = db.execute(
                    """SELECT cash_cents, realized_pnl_cents
                       FROM paper_account WHERE id=1"""
                ).fetchone()
                position = db.execute(
                    """SELECT quantity, cost_basis_cents
                       FROM paper_positions WHERE symbol=?""",
                    (symbol,),
                ).fetchone()
                held, basis = position if position else (0, 0)

                if side == "BUY":
                    debit = gross + fee_cents
                    if debit > cash:
                        raise ValueError("Insufficient hypothetical paper cash")
                    new_quantity = held + quantity
                    new_basis = basis + debit
                    if new_quantity > MAX_SHARES or new_basis > MAX_CENTS:
                        raise ValueError("Paper position exceeds accounting bounds")
                    cash -= debit
                    db.execute(
                        """INSERT INTO paper_positions
                           (symbol, quantity, cost_basis_cents)
                           VALUES (?, ?, ?)
                           ON CONFLICT(symbol) DO UPDATE SET
                           quantity=excluded.quantity,
                           cost_basis_cents=excluded.cost_basis_cents""",
                        (symbol, new_quantity, new_basis),
                    )
                else:
                    if quantity > held:
                        raise ValueError("Cannot sell unowned paper shares")
                    proceeds = gross - fee_cents
                    if proceeds < 0 or cash + proceeds > MAX_CENTS:
                        raise ValueError("Invalid paper sale proceeds")
                    # Integer half-up rounding allocates the entire remaining
                    # basis on the final sale, without floating-point drift.
                    released = (
                        basis if quantity == held else
                        (2 * basis * quantity + held) // (2 * held)
                    )
                    cash += proceeds
                    realized += proceeds - released
                    if abs(realized) > MAX_CENTS:
                        raise ValueError("Paper realized PnL exceeds accounting bounds")
                    if quantity == held:
                        db.execute(
                            "DELETE FROM paper_positions WHERE symbol=?",
                            (symbol,),
                        )
                    else:
                        db.execute(
                            """UPDATE paper_positions
                               SET quantity=?, cost_basis_cents=?
                               WHERE symbol=?""",
                            (held - quantity, basis - released, symbol),
                        )

                db.execute(
                    """UPDATE paper_account
                       SET cash_cents=?, realized_pnl_cents=? WHERE id=1""",
                    (cash, realized),
                )
                db.execute(
                    """INSERT INTO paper_fills
                       (event_id, timestamp_utc, symbol, side, quantity,
                        price_cents, fee_cents)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, *payload),
                )
                self._assert_consistent(db)
                db.commit()
                return True
            except Exception:
                db.rollback()
                raise

    def snapshot(self):
        """Return consistent cash/positions and realized PnL; not marked equity."""
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                self._assert_consistent(db)
                start, cash, realized = db.execute(
                    """SELECT starting_cash_cents, cash_cents,
                              realized_pnl_cents
                       FROM paper_account WHERE id=1"""
                ).fetchone()
                positions = {
                    symbol: {
                        "quantity": quantity,
                        "cost_basis": _money(basis),
                    }
                    for symbol, quantity, basis in db.execute(
                        """SELECT symbol, quantity, cost_basis_cents
                           FROM paper_positions ORDER BY symbol"""
                    )
                }
                count = db.execute(
                    "SELECT COUNT(*) FROM paper_fills"
                ).fetchone()[0]
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {
            "starting_cash": _money(start),
            "cash": _money(cash),
            "realized_pnl": _money(realized),
            "positions": positions,
            "fill_count": count,
        }
