"""Historical corruption must fail closed during an optional full audit.

These are offline consistency checks, not provider authentication.
"""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


START = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


@pytest.mark.parametrize("column, corrupt_value", [
    ("open", "999.00"),       # breaks OHLC ordering
    ("low", "500.50"),        # low above other prices
    ("volume", -1),           # invalid whole-share volume
    ("volume", "not-an-int"), # invalid SQLite storage type
    ("minute_utc", "2026-11-02T15:00:00+00:00"),  # noncanonical UTC
    ("received_utc", "2026-11-02T15:01:10+00:00"),  # noncanonical UTC
])
def test_full_audit_rejects_older_corruption_outside_fast_window(
    tmp_path, column, corrupt_value
):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    for i in range(4):
        minute = START + timedelta(minutes=i)
        assert journal.record(
            feed="alpaca-iex", symbol="SPY", minute=minute,
            received_at=minute + timedelta(minutes=1, seconds=10),
            open="500.01", high="500.03", low="500.00", close="500.02",
            volume=1000,
        )

    with sqlite3.connect(journal.db_path) as db:
        db.execute(
            f"UPDATE paper_observations SET {column}=? "
            "WHERE feed='alpaca-iex' AND symbol='SPY' AND minute_utc=?",
            (corrupt_value, START.astimezone(ZoneInfo("UTC")).isoformat(timespec="microseconds")),
        )
        assert db.total_changes == 1

    as_of = START + timedelta(minutes=4, seconds=20)
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=as_of)
    with pytest.raises(ValueError, match="Corrupt"):
        journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=as_of)
