"""Full-history, same-snapshot observation audit remains research-only."""

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


T0 = datetime(2026, 11, 2, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def _record(journal, minute=T0, symbol="SPY"):
    return journal.record(
        feed="alpaca-iex", symbol=symbol, minute=minute,
        received_at=minute + timedelta(minutes=1, seconds=10),
        open="500.01", high="500.03", low="500.00", close="500.02",
        volume=1000,
    )


def _filled(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    for index in range(4):
        assert _record(journal, T0 + timedelta(minutes=index))
    return journal


def _now():
    return T0 + timedelta(minutes=4, seconds=20)


def test_full_audit_returns_same_fresh_snapshot_and_handles_empty_partition(tmp_path):
    journal = _filled(tmp_path)
    expected = journal.latest(feed="alpaca-iex", symbol="SPY", as_of=_now())
    assert journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=_now()) == expected
    assert journal.audited_latest(feed="alpaca-iex", symbol="AAPL", as_of=_now()) is None
    assert journal.audited_latest(feed="alpaca-iex", symbol="SPY",
                                  as_of=_now().astimezone(timezone.utc)) == expected
    with sqlite3.connect(journal.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0] == 4


def test_full_audit_catches_corrupt_old_row_that_fast_reader_cannot_see(tmp_path):
    journal = _filled(tmp_path)
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET open='NaN' WHERE minute_utc=?",
                   (T0.astimezone(timezone.utc).isoformat(timespec="microseconds"),))
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=_now())
    with pytest.raises(ValueError, match="Corrupt"):
        journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=_now())
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET open='500.01' WHERE open='NaN'")
    assert journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=_now())


def test_full_audit_catches_old_receipt_reversal(tmp_path):
    journal = _filled(tmp_path)
    first_stamp = T0.astimezone(timezone.utc).isoformat(timespec="microseconds")
    delayed_receipt = (T0 + timedelta(minutes=2, seconds=50)).astimezone(
        timezone.utc).isoformat(timespec="microseconds")
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET received_utc=? WHERE minute_utc=?",
                   (delayed_receipt, first_stamp))
    # Both rows remain individually plausible; only history ordering fails.
    assert journal.latest(feed="alpaca-iex", symbol="SPY", as_of=_now())
    with pytest.raises(ValueError, match="chronology"):
        journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=_now())


@pytest.mark.parametrize("as_of", [
    T0 + timedelta(minutes=4, seconds=9),
    T0 + timedelta(minutes=7),
])
def test_full_audit_rejects_future_or_stale_latest_snapshot(tmp_path, as_of):
    journal = _filled(tmp_path)
    with pytest.raises(ValueError, match="Stale or future"):
        journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=as_of)


@pytest.mark.parametrize("changes, message", [
    ({"feed": "alpaca-sip"}, "feed"),
    ({"symbol": "spy"}, "symbol"),
    ({"as_of": datetime(2026, 11, 2, 14, 0)}, "timezone-aware"),
])
def test_full_audit_rejects_invalid_scope_or_clock(tmp_path, changes, message):
    journal = _filled(tmp_path)
    kwargs = {"feed": "alpaca-iex", "symbol": "SPY", "as_of": _now()}
    kwargs.update(changes)
    with pytest.raises(ValueError, match=message):
        journal.audited_latest(**kwargs)


def test_full_audit_checks_only_requested_partition(tmp_path):
    journal = _filled(tmp_path)
    assert _record(journal, symbol="AAPL")
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET high='NaN' WHERE symbol='AAPL'")
    assert journal.audited_latest(feed="alpaca-iex", symbol="SPY", as_of=_now())
    with pytest.raises(ValueError, match="Corrupt"):
        journal.audited_latest(feed="alpaca-iex", symbol="AAPL",
                              as_of=T0 + timedelta(minutes=2))
