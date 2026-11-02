"""Offline, broker-disconnected point-in-time minute-bar observation journal.

This is an integration seam for a future authenticated data reader, not a
provider client, live trading worker, or proof of market-data authenticity.
It never sends orders or records paper fills. Only completed regular-session
minute bars may be inserted; an immutable SQLite key makes retries harmless.
"""

import re
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")
_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")
_NEW_YORK = ZoneInfo("America/New_York")
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
    if type(value) is str and not _DECIMAL_TEXT.fullmatch(value):
        raise ValueError("Invalid observation price")
    try:
        number = Decimal(value)
        if (not number.is_finite() or not 0 < number <= _MAX_PRICE
                or number != number.quantize(_PRICE_TICK)):
            raise ValueError("Invalid observation price")
    except (InvalidOperation, OverflowError):
        raise ValueError("Invalid observation price") from None
    return format(number.normalize(), "f")


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
        existed = Path(self.db_path).exists()
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
        stamp = minute_utc.isoformat(timespec="microseconds")
        payload = (*prices, volume)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    """SELECT open, high, low, close, volume FROM paper_observations
                       WHERE feed=? AND symbol=? AND minute_utc=?""",
                    (feed, symbol, stamp),
                ).fetchone()
                if row is not None:
                    if row != payload:
                        raise ValueError("Conflicting observation replay")
                    db.commit()
                    return False
                # A completed minute cannot be known before its closing
                # boundary. Reject stale snapshots masquerading as live.
                if not (minute_utc + timedelta(minutes=1) <= received_utc
                        <= minute_utc + timedelta(minutes=3)):
                    raise ValueError("Incomplete or stale observation")
                latest = db.execute(
                    """SELECT MAX(minute_utc) FROM paper_observations
                       WHERE feed=? AND symbol=?""", (feed, symbol)
                ).fetchone()[0]
                if latest is not None and stamp <= latest:
                    raise ValueError("Out-of-order observation")
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
            row = db.execute(
                """SELECT minute_utc, open, high, low, close, volume, received_utc
                   FROM paper_observations WHERE feed=? AND symbol=?
                   ORDER BY minute_utc DESC LIMIT 1""", (feed, symbol)
            ).fetchone()
        if row is None:
            return None
        minute, opening, high, low, close, volume, received = row
        try:
            instant = datetime.fromisoformat(minute)
            receipt = datetime.fromisoformat(received)
            if (instant.astimezone(timezone.utc).isoformat(timespec="microseconds") != minute
                    or receipt.astimezone(timezone.utc).isoformat(timespec="microseconds") != received
                    or instant.second or instant.microsecond
                    or instant.astimezone(_NEW_YORK).weekday() >= 5
                    or not time(9, 30) <= instant.astimezone(_NEW_YORK).time() < time(16, 0)
                    or not instant + timedelta(minutes=1) <= receipt <= instant + timedelta(minutes=3)
                    or type(volume) is not int or not 0 <= volume <= _MAX_VOLUME):
                raise ValueError("Corrupt observation journal row")
            values = tuple(_price(value) for value in (opening, high, low, close))
            if values != (opening, high, low, close):
                raise ValueError("Corrupt observation journal row")
            o, h, l, c = (Decimal(value) for value in values)
            if h < max(o, l, c) or l > min(o, h, c):
                raise ValueError("Corrupt observation journal row")
        except (TypeError, AttributeError, ValueError, OverflowError) as error:
            raise ValueError("Corrupt observation journal row") from error
        if not receipt <= as_of_utc <= instant + timedelta(minutes=3):
            raise ValueError("Stale or future observation snapshot")
        return {"feed": feed, "symbol": symbol, "minute_utc": minute,
                "open": opening, "high": high, "low": low, "close": close,
                "volume": volume, "received_utc": received}
