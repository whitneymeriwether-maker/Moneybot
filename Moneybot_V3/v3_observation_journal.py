"""Offline, broker-disconnected point-in-time minute-bar observation journal.

This is an integration seam for a future authenticated data reader, not a
provider client, live trading worker, or proof of market-data authenticity.
It never sends orders or records paper fills. Only completed regular-session
minute bars may be inserted; an immutable SQLite key makes retries harmless.
"""

import os
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")
_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")
_NEW_YORK = ZoneInfo("America/New_York")
# Serialize schema creation within this process; SQLite serializes the writes.
# An atomic exclusive file creation below elects one initializer across processes.
_INITIALIZE_LOCK = threading.Lock()
_MAX_VOLUME = (1 << 53) - 1
_MAX_PRICE = Decimal("1000000000")
_PRICE_TICK = Decimal("0.000001")
_COLUMNS = ("feed", "symbol", "minute_utc", "open", "high", "low", "close", "volume", "received_utc")


def _utc_stamp(value):
    if (type(value) is not datetime or value.tzinfo is None
            or value.utcoffset() is None):
        raise ValueError("Observation timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _price(value):
    if type(value) not in (str, Decimal):
        raise ValueError("Observation prices require decimal text or Decimal")
    if type(value) is str and (len(value) > 17 or not _DECIMAL_TEXT.fullmatch(value)):
        raise ValueError("Invalid observation price")
    try:
        number = Decimal(value)
        if (not number.is_finite() or not 0 < number <= _MAX_PRICE
                or number != number.quantize(_PRICE_TICK)):
            raise ValueError("Invalid observation price")
    except (InvalidOperation, OverflowError):
        raise ValueError("Invalid observation price") from None
    return format(number.normalize(), "f")



def _validate_stored_row(row):
    """Validate one complete stored observation; return its UTC instants.

    This checks structural and declared temporal consistency, not provider
    authenticity or protection against coordinated SQLite-file tampering.
    """
    try:
        minute, opening, highest, lowest, closing, volume, received = row
        if type(minute) is not str or type(received) is not str:
            raise ValueError("Invalid stored timestamps")
        instant = datetime.fromisoformat(minute)
        receipt = datetime.fromisoformat(received)
        local = instant.astimezone(_NEW_YORK)
        if (_utc_stamp(instant).isoformat(timespec="microseconds") != minute
                or _utc_stamp(receipt).isoformat(timespec="microseconds") != received
                or instant.second or instant.microsecond
                or local.weekday() >= 5
                or not time(9, 30) <= local.time() < time(16, 0)
                or not instant + timedelta(minutes=1) <= receipt <= instant + timedelta(minutes=3)
                or type(volume) is not int or not 0 <= volume <= _MAX_VOLUME):
            raise ValueError("Invalid stored observation timing or volume")
        values = tuple(_price(value) for value in (opening, highest, lowest, closing))
        if values != (opening, highest, lowest, closing):
            raise ValueError("Noncanonical stored observation price")
        o, h, l, c = (Decimal(value) for value in values)
        if h < max(o, l, c) or l > min(o, h, c):
            raise ValueError("Inconsistent stored observation OHLC")
        return instant, receipt
    except (TypeError, AttributeError, ValueError, OverflowError) as error:
        raise ValueError("Corrupt observation journal row") from error


class PaperObservationJournal:
    """Durable research observations, without fills, credentials, or orders.

    The caller must authenticate the market-data provider independently.
    The 'alpaca-iex' label is a declaration, not authentication. Only one
    symbol's completed, fresh, regular-session minute may be recorded per
    feed and UTC minute. Historical replays belong in the backtest pipeline.
    """

    def __init__(self, db_path):
        if (not isinstance(db_path, (str, Path)) or not str(db_path).strip()
                or str(db_path) == ":memory:"):
            raise ValueError("A persistent observation SQLite path is required")
        self.db_path = str(db_path)
        with _INITIALIZE_LOCK:
            # Atomic creation distinguishes the first initializer from processes
            # that observe its file before the schema transaction commits.
            # A crashed first initializer leaves an empty file, which fails closed.
            try:
                fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                existed = True
            else:
                existed = False
                os.close(fd)
            with closing(self._connect()) as db:
                try:
                    db.execute("BEGIN IMMEDIATE")
                    tables = {name for (name,) in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_observations'"
                    )}
                    if existed and not tables:
                        raise ValueError("Existing file is not an observation journal")
                    db.execute("""CREATE TABLE IF NOT EXISTS paper_observations (
                        feed TEXT NOT NULL, symbol TEXT NOT NULL,
                        minute_utc TEXT NOT NULL, open TEXT NOT NULL,
                        high TEXT NOT NULL, low TEXT NOT NULL,
                        close TEXT NOT NULL, volume INTEGER NOT NULL,
                        received_utc TEXT NOT NULL,
                        PRIMARY KEY(feed, symbol, minute_utc)
                    )""")
                    schema = list(db.execute("PRAGMA table_info(paper_observations)"))
                    columns = tuple(row[1] for row in schema)
                    if (columns != _COLUMNS
                            or tuple(row[2] for row in schema) != (
                                "TEXT", "TEXT", "TEXT", "TEXT", "TEXT",
                                "TEXT", "TEXT", "INTEGER", "TEXT"
                            )
                            or tuple(row[5] for row in schema) != (1, 2, 3, 0, 0, 0, 0, 0, 0)
                            or any(row[3] != 1 for row in schema)):
                        raise ValueError("Unsupported observation journal schema")
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
    
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def record(self, *, feed, symbol, minute, received_at, open, high, low, close, volume):
        """Insert a completed minute; True=new, False=identical retry.

        A later or conflicting replay cannot rewrite an observation. Receipt
        time is not part of the idempotency key, allowing delayed retries.
        This does not authenticate the source or prove a quote was executable.
        """
        if feed != "alpaca-iex" or type(feed) is not str:
            raise ValueError("Unsupported declared research feed")
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ValueError("Invalid observation symbol")
        minute_utc = _utc_stamp(minute)
        received_utc = _utc_stamp(received_at)
        if minute_utc.second or minute_utc.microsecond:
            raise ValueError("Observation minute must be UTC-minute aligned")
        local = minute_utc.astimezone(_NEW_YORK)
        if local.weekday() >= 5 or not time(9, 30) <= local.time() < time(16, 0):
            raise ValueError("Observation outside eligible regular session")
        if type(volume) is not int or not 0 <= volume <= _MAX_VOLUME:
            raise ValueError("Invalid whole-share observation volume")
        prices = tuple(_price(value) for value in (open, high, low, close))
        opening, highest, lowest, closing_price = (Decimal(value) for value in prices)
        if highest < max(opening, lowest, closing_price) or lowest > min(opening, highest, closing_price):
            raise ValueError("Inconsistent observation OHLC")
        # Even an identical retry must not claim an impossible pre-close receipt.
        # Delayed retries remain valid because their receipt is not stored.
        if received_utc < minute_utc + timedelta(minutes=1):
            raise ValueError("Incomplete observation: receipt precedes minute completion")
        stamp = minute_utc.isoformat(timespec="microseconds")
        payload = (*prices, volume)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    """SELECT minute_utc, open, high, low, close, volume, received_utc
                       FROM paper_observations
                       WHERE feed=? AND symbol=? AND minute_utc=?""",
                    (feed, symbol, stamp),
                ).fetchone()
                if row is not None:
                    _validate_stored_row(row)
                    if row[1:6] != payload:
                        raise ValueError("Conflicting observation replay")
                    db.commit()
                    return False
                # A completed minute cannot be known before its closing
                # boundary. Reject stale snapshots masquerading as live.
                if not (minute_utc + timedelta(minutes=1) <= received_utc
                        <= minute_utc + timedelta(minutes=3)):
                    raise ValueError("Incomplete or stale observation")

                latest = db.execute(
                    """SELECT minute_utc, open, high, low, close, volume, received_utc
                       FROM paper_observations WHERE feed=? AND symbol=?
                       ORDER BY minute_utc DESC LIMIT 1""", (feed, symbol)
                ).fetchone()
                if latest is not None:
                    try:
                        _, previous_receipt = _validate_stored_row(latest)
                    except ValueError as error:
                        raise ValueError("Corrupt prior observation receipt or row") from error
                    if stamp <= latest[0]:
                        raise ValueError("Out-of-order observation")
                    # Declared receipt instants must not reverse across rows.
                    if received_utc < previous_receipt:
                        raise ValueError("Observation receipt chronology reversal")
                db.execute(
                    """INSERT INTO paper_observations
                       (feed, symbol, minute_utc, open, high, low, close,
                        volume, received_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (feed, symbol, stamp, *payload,
                     received_utc.isoformat(timespec="microseconds")),
                )
                db.commit()
                return True
            except BaseException:
                db.rollback()
                raise

    def latest(self, *, feed, symbol, as_of):
        """Read a recent completed observation, never a stale last-known quote.

        The caller supplies as_of; this cannot authenticate its clock or feed.
        """
        if feed != "alpaca-iex" or type(feed) is not str:
            raise ValueError("Unsupported declared research feed")
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ValueError("Invalid observation symbol")
        as_of_utc = _utc_stamp(as_of)
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT minute_utc, open, high, low, close, volume, received_utc
                   FROM paper_observations WHERE feed=? AND symbol=?
                   ORDER BY minute_utc DESC LIMIT 2""", (feed, symbol)
            ).fetchall()
        if not rows:
            return None

        row = rows[0]
        try:
            instant, receipt = _validate_stored_row(row)
            if len(rows) == 2:
                previous_minute, previous_receipt = _validate_stored_row(rows[1])
                if previous_minute >= instant or previous_receipt > receipt:
                    raise ValueError("Corrupt observation receipt chronology")
        except ValueError as error:
            raise ValueError("Corrupt observation journal row") from error
        minute, opening, high, low, close, volume, received = row
        if not receipt <= as_of_utc <= instant + timedelta(minutes=3):
            raise ValueError("Stale or future observation snapshot")
        return {"feed": feed, "symbol": symbol, "minute_utc": minute,
                "open": opening, "high": high, "low": low, "close": close,
                "volume": volume, "received_utc": received}

    def audited_latest(self, *, feed, symbol, as_of):
        """Read the latest observation after validating the entire symbol history.

        Unlike latest(), this scans every recorded row for this feed/symbol in
        one consistent SQLite read snapshot. It detects corrupt older rows and
        receipt reversals beyond the fast reader's two-row window. It is
        intentionally O(history size), read-only, and unsuitable as an atomic
        execution-time risk decision or proof of provider authenticity.
        """
        if type(feed) is not str or feed != "alpaca-iex":
            raise ValueError("Unsupported declared research feed")
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ValueError("Invalid observation symbol")
        as_of_utc = _utc_stamp(as_of)
        previous_minute = previous_receipt = None
        last = None
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                for row in db.execute(
                    """SELECT minute_utc, open, high, low, close, volume, received_utc
                       FROM paper_observations WHERE feed=? AND symbol=?
                       ORDER BY minute_utc ASC""", (feed, symbol)
                ):
                    instant, receipt = _validate_stored_row(row)
                    if previous_minute is not None and (
                        instant <= previous_minute or receipt < previous_receipt
                    ):
                        raise ValueError("Corrupt observation journal chronology")
                    previous_minute, previous_receipt = instant, receipt
                    last = row
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if last is None:
            return None
        if not previous_receipt <= as_of_utc <= previous_minute + timedelta(minutes=3):
            raise ValueError("Stale or future observation snapshot")
        minute, opening, high, low, close, volume, received = last
        return {"feed": feed, "symbol": symbol, "minute_utc": minute,
                "open": opening, "high": high, "low": low, "close": close,
                "volume": volume, "received_utc": received}
