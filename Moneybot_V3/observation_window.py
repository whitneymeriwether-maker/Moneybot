"""Restart-safe authenticated observation window for V3 paper research.

This is NOT a fill ledger or trading scheduler. A SQLite transaction rejects
duplicate/out-of-order quotes across worker restarts; only the last 100
observations are retained. No order submission path exists.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .market_analysis import analyze_window


class ObservationWindow:
    def __init__(self, path):
        if not isinstance(path, (str, Path)) or not str(path).strip() or str(path) == ":memory:":
            raise ValueError("Persistent observation path required")
        self.path = str(path)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observations (
                symbol TEXT NOT NULL, timestamp_utc TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(symbol,timestamp_utc))""")

    def append(self, observation):
        if type(observation) is not dict or observation.get("authenticated") is not True or observation.get("execution_authorized") is not False or observation.get("provider") != "alpaca":
            raise ValueError("Authenticated research observation required")
        symbol = observation.get("symbol")
        stamp = observation.get("timestamp_utc")
        if type(symbol) is not str or not symbol.isascii() or not symbol.replace(".", "").replace("-", "").isalnum() or len(symbol) > 10 or symbol != symbol.upper():
            raise ValueError("Invalid symbol")
        if type(stamp) is not str:
            raise ValueError("Missing timestamp")
        try:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid timestamp") from None
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Timestamp must be aware")
        utc = instant.astimezone(timezone.utc).isoformat(timespec="microseconds")
        if utc != stamp:
            raise ValueError("Noncanonical UTC timestamp")
        if type(observation.get("price")) is not str:
            raise ValueError("Invalid price")
        # Use analysis validator for numeric shape with a controlled window.
        from decimal import Decimal, InvalidOperation
        try:
            p = Decimal(observation["price"])
            if not p.is_finite() or p <= 0 or p != p.quantize(Decimal(".01")):
                raise ValueError("Invalid price")
        except (InvalidOperation, OverflowError):
            raise ValueError("Invalid price") from None
        payload = json.dumps(observation, sort_keys=True)
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT MAX(timestamp_utc) FROM observations WHERE symbol=?", (symbol,)).fetchone()[0]
            if last is not None and utc <= last:
                db.rollback()
                raise ValueError("Duplicate or out-of-order observation")
            db.execute("INSERT INTO observations VALUES (?,?,?)", (symbol, utc, payload))
            db.execute("""DELETE FROM observations WHERE symbol=? AND timestamp_utc NOT IN
                       (SELECT timestamp_utc FROM observations WHERE symbol=? ORDER BY timestamp_utc DESC LIMIT 100)""", (symbol, symbol))
            db.commit()

    def analyze(self, symbol, now):
        with sqlite3.connect(self.path, timeout=10) as db:
            rows = db.execute("SELECT payload FROM observations WHERE symbol=? ORDER BY timestamp_utc", (symbol,)).fetchall()
        return analyze_window([json.loads(row[0]) for row in rows], symbol=symbol, now=now)
