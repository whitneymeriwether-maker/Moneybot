"""Bound untrusted journal inputs and reject impossible duplicate receipt claims.

These are local declared-timestamp and input-size checks, not independent
provider authentication or proof of an executable market-data feed.
"""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from v3_observation_journal import PaperObservationJournal


T0 = datetime(2026, 11, 2, 9, 45, tzinfo=ZoneInfo("America/New_York"))


def observation(**changes):
    values = dict(
        feed="alpaca-iex", symbol="SPY", minute=T0,
        received_at=T0 + timedelta(minutes=1, seconds=10),
        open="500.01", high="500.03", low="500.00",
        close="500.02", volume=1000,
    )
    values.update(changes)
    return values


def test_identical_retry_with_preclose_receipt_fails_closed(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**observation()) is True
    with pytest.raises(ValueError, match="precedes minute completion"):
        journal.record(**observation(received_at=T0 + timedelta(seconds=59)))
    with sqlite3.connect(journal.db_path) as db:
        assert db.execute(
            "SELECT count(*), max(received_utc) FROM paper_observations"
        ).fetchone() == (
            1, (T0 + timedelta(minutes=1, seconds=10)).astimezone(
                ZoneInfo("UTC")
            ).isoformat(timespec="microseconds"),
        )
    assert journal.record(**observation(received_at=T0 + timedelta(hours=1))) is False


def test_preclose_first_insert_fails_without_writing(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    with pytest.raises(ValueError, match="precedes minute completion"):
        journal.record(**observation(received_at=T0 + timedelta(seconds=59)))
    with sqlite3.connect(journal.db_path) as db:
        assert db.execute("SELECT count(*) FROM paper_observations").fetchone() == (0,)


@pytest.mark.parametrize("price", [
    "9" * 10000,
    "0." + "0" * 10000 + "1",
])
def test_oversized_price_text_is_rejected_without_writing(tmp_path, price):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    with pytest.raises(ValueError, match="Invalid observation price"):
        journal.record(**observation(open=price))
    with sqlite3.connect(journal.db_path) as db:
        assert db.execute("SELECT count(*) FROM paper_observations").fetchone() == (0,)


def test_max_length_valid_price_text_is_not_rejected_for_length(tmp_path):
    journal = PaperObservationJournal(tmp_path / "journal.sqlite")
    assert journal.record(**observation(
        open="1000000000.000000",
        high="1000000000.000000",
        low="1000000000.000000",
        close="1000000000.000000",
    ))
