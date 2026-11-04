"""Research-only observation persistence, ordering, and fail-closed replay."""

import sqlite3
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


NY = ZoneInfo("America/New_York")
T0 = datetime(2026, 11, 2, 9, 45, tzinfo=NY)


def observation(minute=T0, **overrides):
    payload = dict(feed="alpaca-iex", symbol="SPY", minute=minute,
                   received_at=minute + timedelta(minutes=1, seconds=10),
                   open="500.01", high="500.03", low="500.00",
                   close="500.02", volume=1000)
    payload.update(overrides)
    return payload


def test_persists_across_restart_and_exact_retry_is_harmless(tmp_path):
    path = tmp_path / "observations.sqlite"
    journal = PaperObservationJournal(path)
    assert journal.record(**observation()) is True
    assert journal.record(**observation(received_at=T0 + timedelta(hours=1))) is False
    reopened = PaperObservationJournal(path)
    latest = reopened.latest(feed="alpaca-iex", symbol="SPY", as_of=T0 + timedelta(minutes=2))
    assert latest["close"] == "500.02"
    assert latest["volume"] == 1000
    assert latest["minute_utc"] == T0.astimezone(timezone.utc).isoformat(timespec="microseconds")
    assert reopened.latest(feed="alpaca-iex", symbol="AAPL", as_of=T0 + timedelta(minutes=2)) is None


def test_conflicting_and_out_of_order_replay_fails_without_mutating(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**observation())
    with pytest.raises(ValueError, match="Conflicting"):
        journal.record(**observation(close="500.03"))
    assert journal.record(**observation(T0 + timedelta(minutes=2)))
    with pytest.raises(ValueError, match="Out-of-order"):
        journal.record(**observation(T0 + timedelta(minutes=1)))
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=T0 + timedelta(minutes=4))["close"] == "500.02"


@pytest.mark.parametrize("changes, message", [
    ({"feed": "alpaca-sip"}, "feed"),
    ({"symbol": "spy"}, "symbol"),
    ({"minute": T0.replace(second=1)}, "minute"),
    ({"minute": T0.replace(hour=9, minute=29)}, "session"),
    ({"minute": T0 + timedelta(days=5)}, "session"),
    ({"received_at": T0 + timedelta(seconds=59)}, "Incomplete"),
    ({"received_at": T0 + timedelta(minutes=4)}, "Incomplete"),
    ({"volume": True}, "volume"),
    ({"volume": (1 << 53)}, "volume"),
    ({"volume": -1}, "volume"),
    ({"open": 500.01}, "decimal"),
    ({"high": "500.00"}, "OHLC"),
    ({"close": "NaN"}, "price"),
    ({"close": "5e2"}, "price"),
    ({"close": " 500.00 "}, "price"),
    ({"close": "500.0000001"}, "price"),
    ({"close": "1000000001"}, "price"),
])
def test_rejects_untrusted_or_incomplete_observations(tmp_path, changes, message):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    with pytest.raises(ValueError, match=message):
        journal.record(**observation(**changes))
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=T0 + timedelta(minutes=2)) is None


def test_existing_unrelated_database_cannot_be_reinitialized(tmp_path):
    path = tmp_path / "existing.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (x INTEGER)")
    with pytest.raises(ValueError, match="Existing file"):
        PaperObservationJournal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='unrelated'").fetchone()


def test_utc_instant_is_used_for_dst_and_cross_offset_inputs(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    utc = T0.astimezone(timezone.utc)
    assert journal.record(**observation(minute=utc, received_at=utc+timedelta(minutes=1)))
    assert journal.record(**observation(minute=T0+timedelta(minutes=1)))
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=T0 + timedelta(minutes=3))["minute_utc"] == (
        utc+timedelta(minutes=1)).isoformat(timespec="microseconds")


def test_simultaneous_identical_observations_are_serialized(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: journal.record(**observation()), range(4)))
    assert results.count(True) == 1
    assert results.count(False) == 3


def test_malformed_existing_schema_cannot_disable_uniqueness(tmp_path):
    path = tmp_path / "journal.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE paper_observations (
            feed TEXT NOT NULL, symbol TEXT NOT NULL, minute_utc TEXT NOT NULL,
            open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL,
            close TEXT NOT NULL, volume INTEGER NOT NULL,
            received_utc TEXT NOT NULL)""")
    with pytest.raises(ValueError, match="schema"):
        PaperObservationJournal(path)


def test_corrupt_stored_observation_is_not_returned(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    journal.record(**observation())
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET close='NaN'")
    with pytest.raises(ValueError, match="Corrupt"):
        journal.latest(feed="alpaca-iex", symbol="SPY", as_of=T0 + timedelta(minutes=2))


def test_latest_rejects_stale_or_pre_receipt_snapshots(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    journal.record(**observation())
    for as_of in (T0 + timedelta(seconds=61), T0 + timedelta(minutes=4)):
        with pytest.raises(ValueError, match="Stale or future"):
            journal.latest(feed="alpaca-iex", symbol="SPY", as_of=as_of)
    with pytest.raises(ValueError, match="timezone-aware"):
        journal.latest(feed="alpaca-iex", symbol="SPY", as_of=datetime(2026, 11, 2))


@pytest.mark.parametrize("wrong_column, wrong_type", [
    ("volume", "TEXT"),
    ("close", "INTEGER"),
    ("received_utc", "BLOB"),
])
def test_existing_journal_rejects_incompatible_declared_column_types(tmp_path, wrong_column, wrong_type):
    path = tmp_path / "journal.sqlite"
    columns = [
        ("feed", "TEXT"), ("symbol", "TEXT"), ("minute_utc", "TEXT"),
        ("open", "TEXT"), ("high", "TEXT"), ("low", "TEXT"),
        ("close", "TEXT"), ("volume", "INTEGER"), ("received_utc", "TEXT"),
    ]
    declarations = ", ".join(
        f"{name} {wrong_type if name == wrong_column else kind} NOT NULL"
        for name, kind in columns
    )
    with sqlite3.connect(path) as db:
        db.execute(
            f"CREATE TABLE paper_observations ({declarations}, "
            "PRIMARY KEY(feed, symbol, minute_utc))"
        )
    with pytest.raises(ValueError, match="schema"):
        PaperObservationJournal(path)


def _open_journal_in_child(path):
    journal = PaperObservationJournal(path)
    return journal.db_path


def test_independent_processes_can_initialize_same_cold_journal(tmp_path):
    path = tmp_path / "multiprocess.sqlite"
    with ProcessPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_open_journal_in_child, [str(path)] * 24))
    assert results == [str(path)] * 24
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone() == (0,)


def test_empty_preexisting_file_is_not_silently_provisioned(tmp_path):
    path = tmp_path / "empty.sqlite"
    path.touch()
    with pytest.raises(ValueError, match="Existing file"):
        PaperObservationJournal(path)
