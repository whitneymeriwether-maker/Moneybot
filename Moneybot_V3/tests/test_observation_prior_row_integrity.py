"""Research observation journal fails closed on corrupted prior stored rows.

These checks validate locally stored data only. They do not authenticate
market-data providers, receipt clocks, or executable market liquidity.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


T0 = datetime(2026, 11, 2, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def sample(minute=T0):
    return dict(
        feed="alpaca-iex", symbol="SPY", minute=minute,
        received_at=minute + timedelta(minutes=1, seconds=10),
        open="500.01", high="500.03", low="500.00",
        close="500.02", volume=1000,
    )


def utc_text(instant):
    return instant.astimezone(timezone.utc).isoformat(timespec="microseconds")


def change_row(journal, column, value, minute=T0):
    # The column names are fixed test constants, never untrusted input.
    with sqlite3.connect(journal.db_path) as db:
        db.execute(
            f"UPDATE paper_observations SET {column}=? WHERE minute_utc=?",
            (value, utc_text(minute)),
        )


@pytest.mark.parametrize("column,value", [
    ("open", "NaN"),
    ("high", "499.00"),
    ("volume", -1),
    ("received_utc", utc_text(T0 + timedelta(seconds=30))),
    ("minute_utc", utc_text(T0 + timedelta(seconds=1))),
    ("minute_utc", utc_text(T0 - timedelta(minutes=20))),
])
def test_latest_rejects_corruption_in_immediately_preceding_row(
    tmp_path, column, value
):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**sample())
    assert journal.record(**sample(T0 + timedelta(minutes=1)))
    change_row(journal, column, value)
    with pytest.raises(ValueError, match="Corrupt observation"):
        journal.latest(
            feed="alpaca-iex", symbol="SPY",
            as_of=T0 + timedelta(minutes=2, seconds=20),
        )


@pytest.mark.parametrize("column,value", [
    ("close", "NaN"),
    ("high", "499.00"),
    ("volume", -1),
    ("received_utc", utc_text(T0 + timedelta(seconds=30))),
])
def test_append_refuses_corrupt_latest_row_without_writing(
    tmp_path, column, value
):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**sample())
    change_row(journal, column, value)
    with pytest.raises(ValueError, match="Corrupt prior observation"):
        journal.record(**sample(T0 + timedelta(minutes=1)))
    with sqlite3.connect(journal.db_path) as db:
        assert db.execute("SELECT count(*) FROM paper_observations").fetchone() == (1,)


def test_identical_retry_cannot_hide_corrupted_stored_receipt(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**sample())
    change_row(journal, "received_utc", utc_text(T0 + timedelta(seconds=30)))
    with pytest.raises(ValueError, match="Corrupt observation"):
        journal.record(**sample())


def test_valid_append_succeeds_after_prior_row_repaired(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**sample())
    change_row(journal, "volume", -1)
    with pytest.raises(ValueError, match="Corrupt prior observation"):
        journal.record(**sample(T0 + timedelta(minutes=1)))
    change_row(journal, "volume", 1000)
    assert journal.record(**sample(T0 + timedelta(minutes=1)))
    assert journal.latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=T0 + timedelta(minutes=2, seconds=20),
    )["minute_utc"] == utc_text(T0 + timedelta(minutes=1))
