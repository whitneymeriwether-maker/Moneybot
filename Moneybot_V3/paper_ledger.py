"""Durable, broker-disconnected cash ledger for Moneybot V3 paper research.

This is a local SQLite prototype, NOT a Neon adapter or order execution
service. Only externally supplied hypothetical fills can change its balance.
Amounts are exact cents, quantities are whole shares, and transactions are
atomic. A real paper broker integration must independently verify fills,
market timestamps, risk gates, and execution semantics before calling this.
"""

import re
import sqlite3
from contextlib import closing, contextmanager
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
        # sqlite3.connect() creates a missing file. Capture whether a file
        # existed *before* connecting: an empty or unrelated pre-existing DB
        # must not silently become a new $1,000 paper account after ledger
        # data was lost or the path was accidentally reused.
        existed_before_connect = Path(self.db_path).exists()
        initial = _cents(starting_cash)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                # Existing ledger files must not be silently repaired by
                # CREATE TABLE or reseeded if their account row was deleted.
                # A partial schema is evidence of corruption or an
                # unsupported migration, not a fresh empty account.
                existing_tables = {
                    name for (name,) in db.execute(
                        """SELECT name FROM sqlite_master
                           WHERE type='table' AND name IN
                           ('paper_account', 'paper_positions', 'paper_fills')"""
                    )
                }
                if existing_tables and existing_tables != {
                    "paper_account", "paper_positions", "paper_fills"
                }:
                    raise ValueError("Incomplete existing paper ledger schema")
                if existed_before_connect and not existing_tables:
                    raise ValueError(
                        "Existing SQLite file has no paper ledger schema; "
                        "refusing to initialize a potentially lost account"
                    )
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
                    if existing_tables:
                        raise ValueError(
                            "Missing existing paper account row; refusing to reinitialize"
                        )
                    db.execute(
                        """INSERT INTO paper_account
                        (id, starting_cash_cents, cash_cents, realized_pnl_cents)
                        VALUES (1, ?, ?, 0)""",
                        (initial, initial),
                    )
                elif row[0] != initial:
                    raise ValueError("Existing paper account has different starting cash")
                self._assert_consistent(db)
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
        for symbol, quantity, basis in db.execute(
            "SELECT symbol, quantity, cost_basis_cents FROM paper_positions"
        ):
            if (
                type(symbol) is not str or not _SYMBOL.fullmatch(symbol)
                or type(quantity) is not int or not 0 < quantity <= MAX_SHARES
                or type(basis) is not int or not 0 < basis <= MAX_CENTS
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

    @contextmanager
    def consistent_advisory_read(self):
        """Hold a SQLite writer reservation while auditing and marking.

        This context performs no database writes. BEGIN IMMEDIATE prevents
        ordinary concurrent SQLite fill writers from changing the ledger
        between separate read transactions. Keep the protected work short:
        the O(number of fills) audit can delay other paper workers. This
        does not authenticate data or authorize any execution.
        """
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                self._assert_consistent(db)
                yield
                db.commit()
            except BaseException:
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

    def audit_history(self, *, realized_since=None):
        """Explicitly replay all hypothetical fills and reconcile final state.

        This independent O(number of fills) check detects changes to fill
        records and coordinated balance edits that the basic accounting
        invariant cannot detect. Run before trusting research reports or
        migrating the ledger; do not call on every fill in a large account.
        It is not cryptographic authentication or proof of market execution.

        Optionally replay realized SELL PnL from an aware UTC instant onward.
        This derives a daily risk figure from recorded hypothetical fills,
        not external marks or authenticated exchange executions.
        """
        if realized_since is not None:
            if (
                type(realized_since) is not datetime
                or realized_since.tzinfo is None
                or realized_since.utcoffset() is None
            ):
                raise ValueError("Realized PnL start must be timezone-aware")
            since_stamp = realized_since.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            )
        else:
            since_stamp = None
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                self._assert_consistent(db)
                start, stored_cash, stored_realized = db.execute(
                    """SELECT starting_cash_cents, cash_cents, realized_pnl_cents
                       FROM paper_account WHERE id=1"""
                ).fetchone()
                cash, realized = start, 0
                realized_since_cents = 0
                positions = {}
                previous_timestamp = None
                count = 0
                # ROWID preserves insertion order when several fills share a
                # timestamp; sorting by event ID could invert a buy and sell.
                rows = db.execute(
                    """SELECT event_id, timestamp_utc, symbol, side, quantity,
                              price_cents, fee_cents
                       FROM paper_fills ORDER BY rowid"""
                )
                for event_id, stamp, symbol, side, quantity, price, fee in rows:
                    if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
                        raise ValueError("Corrupt paper fill history: event ID")
                    if type(stamp) is not str:
                        raise ValueError("Corrupt paper fill history: timestamp")
                    try:
                        parsed = datetime.fromisoformat(stamp)
                        canonical = parsed.astimezone(timezone.utc).isoformat(
                            timespec="microseconds"
                        ) if parsed.tzinfo is not None else None
                    except (TypeError, ValueError, OverflowError):
                        canonical = None
                    if stamp != canonical or (
                        previous_timestamp is not None and stamp < previous_timestamp
                    ):
                        raise ValueError("Corrupt paper fill history: timestamp")
                    previous_timestamp = stamp
                    if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
                        raise ValueError("Corrupt paper fill history: symbol")
                    if side not in ("BUY", "SELL") or type(side) is not str:
                        raise ValueError("Corrupt paper fill history: side")
                    if type(quantity) is not int or not 0 < quantity <= MAX_SHARES:
                        raise ValueError("Corrupt paper fill history: quantity")
                    if (
                        type(price) is not int or not 0 < price <= MAX_CENTS
                        or type(fee) is not int or not 0 <= fee <= MAX_CENTS
                    ):
                        raise ValueError("Corrupt paper fill history: money")
                    gross = price * quantity
                    if gross > MAX_CENTS or gross + fee > MAX_CENTS:
                        raise ValueError("Corrupt paper fill history: notional")

                    held, basis = positions.get(symbol, (0, 0))
                    if side == "BUY":
                        debit = gross + fee
                        if debit > cash:
                            raise ValueError("Corrupt paper fill history: overspend")
                        new_quantity, new_basis = held + quantity, basis + debit
                        if new_quantity > MAX_SHARES or new_basis > MAX_CENTS:
                            raise ValueError("Corrupt paper fill history: position bounds")
                        cash -= debit
                        positions[symbol] = (new_quantity, new_basis)
                    else:
                        if quantity > held:
                            raise ValueError("Corrupt paper fill history: unowned sale")
                        proceeds = gross - fee
                        if proceeds < 0 or cash + proceeds > MAX_CENTS:
                            raise ValueError("Corrupt paper fill history: sale proceeds")
                        released = (
                            basis if quantity == held else
                            (2 * basis * quantity + held) // (2 * held)
                        )
                        cash += proceeds
                        realized_change = proceeds - released
                        realized += realized_change
                        if since_stamp is not None and stamp >= since_stamp:
                            realized_since_cents += realized_change
                        if (
                            abs(realized) > MAX_CENTS
                            or abs(realized_since_cents) > MAX_CENTS
                        ):
                            raise ValueError("Corrupt paper fill history: realized PnL")
                        if quantity == held:
                            del positions[symbol]
                        else:
                            positions[symbol] = (held - quantity, basis - released)
                    count += 1

                stored_positions = {
                    symbol: (quantity, basis)
                    for symbol, quantity, basis in db.execute(
                        "SELECT symbol, quantity, cost_basis_cents FROM paper_positions"
                    )
                }
                if (
                    cash != stored_cash or realized != stored_realized
                    or positions != stored_positions
                ):
                    raise ValueError("Corrupt paper fill history: state mismatch")
                db.commit()
            except Exception:
                db.rollback()
                raise
        result = {
            "audited_fills": count,
            "cash": _money(cash),
            "realized_pnl": _money(realized),
        }
        if since_stamp is not None:
            result["realized_since"] = _money(realized_since_cents)
        return result

    def marked_snapshot(self, marks, *, as_of, max_age_seconds=720):
        """Read-only, point-in-time *hypothetical* equity and exposure estimate.

        Each open position needs a positive, exact-cent mark and a timezone-
        aware observation timestamp. Reject missing/extra symbols, stale or
        future observations, and marks preceding that symbol's latest fill.
        The caller supplies as_of: historical reproducibility is intentional,
        but this method cannot authenticate quotes, as_of, or data provenance.
        It is NOT an execution-time risk gate or broker account valuation.
        """
        if (
            not isinstance(as_of, datetime)
            or as_of.tzinfo is None or as_of.utcoffset() is None
        ):
            raise ValueError("Marked snapshot requires timezone-aware as_of")
        if (
            type(max_age_seconds) is not int
            or not 0 <= max_age_seconds <= 86400
        ):
            raise ValueError("Invalid maximum mark age")
        if type(marks) is not dict:
            raise ValueError("Marks must be a symbol-to-observation dictionary")
        as_of_utc = as_of.astimezone(timezone.utc)
        as_of_stamp = as_of_utc.isoformat(timespec="microseconds")

        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                self._assert_consistent(db)
                start, cash, realized = db.execute(
                    """SELECT starting_cash_cents, cash_cents,
                              realized_pnl_cents
                       FROM paper_account WHERE id=1"""
                ).fetchone()
                stored = {
                    symbol: (quantity, basis)
                    for symbol, quantity, basis in db.execute(
                        """SELECT symbol, quantity, cost_basis_cents
                           FROM paper_positions ORDER BY symbol"""
                    )
                }
                if set(marks) != set(stored):
                    raise ValueError("Marks must exactly match open paper positions")
                last_fill = db.execute(
                    "SELECT MAX(timestamp_utc) FROM paper_fills"
                ).fetchone()[0]
                if last_fill is not None and as_of_stamp < last_fill:
                    raise ValueError("Marked snapshot predates a recorded fill")
                latest_by_symbol = dict(db.execute(
                    """SELECT symbol, MAX(timestamp_utc)
                       FROM paper_fills GROUP BY symbol"""
                ))
                positions = {}
                total_market = 0
                total_basis = 0
                for symbol, (quantity, basis) in stored.items():
                    observation = marks[symbol]
                    if (
                        type(observation) is not dict
                        or set(observation) != {"price", "timestamp"}
                    ):
                        raise ValueError("Invalid paper mark observation")
                    stamp = observation["timestamp"]
                    if (
                        not isinstance(stamp, datetime)
                        or stamp.tzinfo is None or stamp.utcoffset() is None
                    ):
                        raise ValueError("Paper mark timestamp must be timezone-aware")
                    mark_utc = stamp.astimezone(timezone.utc)
                    age = (as_of_utc - mark_utc).total_seconds()
                    if not 0 <= age <= max_age_seconds:
                        raise ValueError("Stale or future paper mark")
                    mark_stamp = mark_utc.isoformat(timespec="microseconds")
                    if mark_stamp < latest_by_symbol[symbol]:
                        raise ValueError("Paper mark predates latest symbol fill")
                    price_cents = _cents(observation["price"])
                    market_cents = price_cents * quantity
                    total_market += market_cents
                    total_basis += basis
                    if total_market > MAX_CENTS or cash + total_market > MAX_CENTS:
                        raise ValueError("Marked paper equity exceeds accounting bounds")
                    positions[symbol] = {
                        "quantity": quantity,
                        "cost_basis": _money(basis),
                        "mark_price": _money(price_cents),
                        "mark_timestamp_utc": mark_stamp,
                        "market_value": _money(market_cents),
                        "unrealized_pnl": _money(market_cents - basis),
                    }
                equity = cash + total_market
                unrealized = total_market - total_basis
                total_pnl = realized + unrealized
                if (
                    equity < 0 or abs(unrealized) > MAX_CENTS
                    or abs(total_pnl) > MAX_CENTS
                ):
                    raise ValueError("Marked paper totals exceed accounting bounds")
                # A fully liquidated cash-funded paper account may have
                # exactly zero cash after a total loss. Report that valid
                # terminal state with zero exposure, not a division error.
                # Any open position has a positive mark, so zero equity can
                # only occur with no positions and no market value.
                exposure_pct = (
                    (Decimal(100) * Decimal(total_market) / Decimal(equity))
                    .quantize(Decimal("0.0001"))
                    if equity else Decimal("0.0000")
                )
                count = db.execute(
                    "SELECT COUNT(*) FROM paper_fills"
                ).fetchone()[0]
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {
            "as_of_utc": as_of_stamp,
            "starting_cash": _money(start),
            "cash": _money(cash),
            "realized_pnl": _money(realized),
            "market_value": _money(total_market),
            "equity": _money(equity),
            "unrealized_pnl": _money(unrealized),
            "total_pnl": _money(total_pnl),
            "gross_exposure_pct": str(exposure_pct),
            "positions": positions,
            "fill_count": count,
        }
