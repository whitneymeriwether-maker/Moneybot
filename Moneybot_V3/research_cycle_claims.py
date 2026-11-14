"""Restart-safe, single-claim research cycle scheduling for V3.

This is a durable coordination primitive, NOT an execution scheduler. A claimed
cycle cannot place orders. Callers must separately authenticate market data,
validate risk atomically with ledger writes, and prevent live order routing.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re

_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


def _utc(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Aware datetime required")
    return value.astimezone(timezone.utc)


class ResearchCycleClaims:
    def __init__(self, path):
        if type(path) not in (str, Path) or not str(path).strip() or str(path) == ":memory:":
            raise ValueError("Persistent SQLite path required")
        self.path = str(path)
        # Never silently recreate a lost database if an existing path is corrupt.
        existed = Path(self.path).exists()
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existed and "research_cycles" not in tables:
                raise ValueError("Existing database missing cycle schema")
            db.execute("""CREATE TABLE IF NOT EXISTS research_cycles (
                cycle_key TEXT PRIMARY KEY, claimed_at TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('claimed','completed','failed'))
            )""")
            db.commit()

    def claim(self, cycle_key, *, now):
        """At most one successful claim per deterministic cycle key, across restarts.

        An abandoned cycle remains claimed and requires operator review; never
        auto-replay it because downstream side effects may have occurred.
        """
        if type(cycle_key) is not str or not _KEY.fullmatch(cycle_key):
            raise ValueError("Invalid cycle key")
        timestamp = _utc(now).isoformat(timespec="microseconds")
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "INSERT OR IGNORE INTO research_cycles(cycle_key,claimed_at,state) VALUES(?,?,'claimed')",
                (cycle_key, timestamp))
            db.commit()
            return result.rowcount == 1

    def finish(self, cycle_key, *, succeeded):
        if type(cycle_key) is not str or not _KEY.fullmatch(cycle_key) or type(succeeded) is not bool:
            raise ValueError("Invalid cycle completion")
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "UPDATE research_cycles SET state=? WHERE cycle_key=? AND state='claimed'",
                ("completed" if succeeded else "failed", cycle_key))
            db.commit()
            if result.rowcount != 1:
                raise ValueError("Cycle missing or already finalized")
