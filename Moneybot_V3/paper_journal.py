"""Isolated, durable PAPER-ONLY journal. No broker, market feed, or order execution.

This journal records externally verified simulation events; it does not generate fills.
Never use this database as a live brokerage account or evidence of market execution.
"""
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("Amounts must be decimal strings")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid decimal amount") from exc
    if not number.is_finite() or number < 0 or number.as_tuple().exponent < -8:
        raise ValueError("Amount must be finite, nonnegative, at most 8 decimals")
    return str(number)


class PaperJournal:
    """Atomic, idempotent event journal; deliberately cannot place trades."""

    def __init__(self, path):
        if not path or str(path) == ":memory:":
            raise ValueError("Durable journal requires an on-disk path")
        self.path = str(path)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS paper_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                amount TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def record(self, event_id, event_type, amount, payload=None):
        """Record an observation; duplicate IDs are safe only for identical content."""
        if not isinstance(event_id, str) or not (1 <= len(event_id) <= 128) or not event_id.isascii() or not all(c.isalnum() or c in "-_:" for c in event_id):
            raise ValueError("Invalid event ID")
        if event_type not in ("paper_deposit", "paper_withdrawal", "paper_fill_observation"):
            raise ValueError("Unsupported paper event")
        amount = _amount(amount)
        if not isinstance(payload, dict):
            raise ValueError("Payload must be an explicit dictionary")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(serialized) > 8192:
            raise ValueError("Payload too large")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT event_type, amount, payload FROM paper_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if previous is not None:
                if previous != (event_type, amount, serialized):
                    raise ValueError("Conflicting event ID")
                return False
            db.execute(
                "INSERT INTO paper_events(event_id,event_type,amount,recorded_at,payload) VALUES(?,?,?,?,?)",
                (event_id, event_type, amount, datetime.now(timezone.utc).isoformat(), serialized),
            )
        return True

    def events(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT sequence,event_id,event_type,amount,recorded_at,payload FROM paper_events ORDER BY sequence"
            ).fetchall()
        return [
            dict(sequence=row[0], event_id=row[1], event_type=row[2], amount=row[3],
                 recorded_at=row[4], payload=json.loads(row[5]))
            for row in rows
        ]
