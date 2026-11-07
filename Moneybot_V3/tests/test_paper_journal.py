"""Regression coverage for the isolated paper-only journal."""
import sqlite3
import pytest

from paper_journal import PaperJournal


def test_durable_reopen_and_idempotent_replay(tmp_path):
    path = tmp_path / "paper.sqlite3"
    journal = PaperJournal(path)
    assert journal.record("event-1", "paper_deposit", "1000.00", {}) is True
    assert journal.record("event-1", "paper_deposit", "1000.00", {}) is False
    reopened = PaperJournal(path)
    events = reopened.events()
    assert len(events) == 1
    assert events[0]["amount"] == "1000.00"
    assert events[0]["event_type"] == "paper_deposit"
    assert reopened.record("event-2", "paper_withdrawal", "1.25", {}) is True
    assert [e["sequence"] for e in reopened.events()] == [1, 2]


def test_conflicting_replay_fails_without_mutation(tmp_path):
    journal = PaperJournal(tmp_path / "paper.sqlite3")
    journal.record("one", "paper_deposit", "20", {"source": "manual"})
    with pytest.raises(ValueError, match="Conflicting"):
        journal.record("one", "paper_deposit", "21", {"source": "manual"})
    with pytest.raises(ValueError, match="Conflicting"):
        journal.record("one", "paper_deposit", "20", {"source": "other"})
    assert len(journal.events()) == 1


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0.000000001", "oops", 2.5, True])
def test_invalid_amounts_fail_closed(tmp_path, amount):
    journal = PaperJournal(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError):
        journal.record("bad", "paper_deposit", amount, {})
    assert journal.events() == []


def test_no_implicit_fill_or_in_memory_account(tmp_path):
    with pytest.raises(ValueError):
        PaperJournal(":memory:")
    journal = PaperJournal(tmp_path / "paper.sqlite3")
    with pytest.raises(ValueError):
        journal.record("one", "live_order", "100", {})
    with pytest.raises(ValueError):
        journal.record("two", "paper_fill_observation", "100", None)
    assert journal.events() == []


def test_transaction_rolls_back_on_sqlite_failure(tmp_path):
    journal = PaperJournal(tmp_path / "paper.sqlite3")
    with sqlite3.connect(journal.path) as db:
        db.execute("""CREATE TRIGGER reject_events BEFORE INSERT ON paper_events
                      BEGIN SELECT RAISE(ABORT, 'rejected'); END""")
    with pytest.raises(sqlite3.DatabaseError):
        journal.record("one", "paper_deposit", "10", {})
    assert journal.events() == []
