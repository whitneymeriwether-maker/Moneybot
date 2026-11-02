"""Offline observation receipt chronology must be monotonic and fail closed."""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


T0 = datetime(2026, 11, 2, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def sample(minute, received_at):
    return dict(
        feed="alpaca-iex", symbol="SPY", minute=minute,
        received_at=received_at, open="500.01", high="500.03",
        low="500.00", close="500.02", volume=1000,
    )


def test_reversed_receipt_chronology_is_rejected_without_inserting(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    assert journal.record(**sample(T0, T0 + timedelta(minutes=2, seconds=45)))
    with pytest.raises(ValueError, match="receipt chronology reversal"):
        journal.record(**sample(
            T0 + timedelta(minutes=1),
            T0 + timedelta(minutes=2, seconds=10),
        ))
    assert journal.latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=T0 + timedelta(minutes=2, seconds=50),
    )["minute_utc"] == T0.astimezone(ZoneInfo("UTC")).isoformat(timespec="microseconds")
    assert journal.record(**sample(
        T0 + timedelta(minutes=1),
        T0 + timedelta(minutes=2, seconds=50),
    ))


def test_equal_receipt_instants_can_represent_batch_arrival(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    receipt = T0 + timedelta(minutes=2, seconds=10)
    assert journal.record(**sample(T0, receipt))
    assert journal.record(**sample(T0 + timedelta(minutes=1), receipt))
    assert journal.latest(
        feed="alpaca-iex", symbol="SPY", as_of=receipt,
    )["minute_utc"] == (T0 + timedelta(minutes=1)).astimezone(
        ZoneInfo("UTC")).isoformat(timespec="microseconds")


def test_latest_rejects_corrupt_prior_receipt_chronology(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    journal.record(**sample(T0, T0 + timedelta(minutes=1, seconds=10)))
    journal.record(**sample(
        T0 + timedelta(minutes=1),
        T0 + timedelta(minutes=2, seconds=10),
    ))
    with sqlite3.connect(journal.db_path) as db:
        db.execute(
            "UPDATE paper_observations SET received_utc=? WHERE minute_utc=?",
            ((T0 + timedelta(minutes=2, seconds=45)).astimezone(
                ZoneInfo("UTC")).isoformat(timespec="microseconds"),
             T0.astimezone(ZoneInfo("UTC")).isoformat(timespec="microseconds")),
        )
    with pytest.raises(ValueError, match="Corrupt observation"):
        journal.latest(
            feed="alpaca-iex", symbol="SPY",
            as_of=T0 + timedelta(minutes=2, seconds=20),
        )


def test_append_rejects_corrupt_prior_receipt(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    journal.record(**sample(T0, T0 + timedelta(minutes=1, seconds=10)))
    with sqlite3.connect(journal.db_path) as db:
        db.execute("UPDATE paper_observations SET received_utc='not-a-time'")
    with pytest.raises(ValueError, match="Corrupt prior observation receipt"):
        journal.record(**sample(
            T0 + timedelta(minutes=1),
            T0 + timedelta(minutes=2, seconds=10),
        ))
