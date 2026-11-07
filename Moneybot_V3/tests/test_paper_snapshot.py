"""Conservative journal projection tests; no simulated execution."""
import sqlite3
import pytest

from paper_journal import PaperJournal
from paper_snapshot import paper_cash_snapshot


def test_cash_projection_survives_restart(tmp_path):
    path = tmp_path / "paper.sqlite3"
    journal = PaperJournal(path)
    journal.record("fund", "paper_deposit", "100.25", {})
    journal.record("out", "paper_withdrawal", "20.10", {})
    result = paper_cash_snapshot(path)
    assert result["cash"] == "80.15"
    assert result["event_count"] == 2
    assert result["trading_ready"] is False
    assert result["paper_trades"] is None
    assert result["performance"] is None
    assert result["verification"] == "journal_only_not_broker_or_market_verified"


def test_overdraft_fails_closed(tmp_path):
    path = tmp_path / "paper.sqlite3"
    PaperJournal(path).record("out", "paper_withdrawal", "1", {})
    with pytest.raises(ValueError, match="overdraft"):
        paper_cash_snapshot(path)


def test_fill_observation_cannot_be_projected_as_verified(tmp_path):
    path = tmp_path / "paper.sqlite3"
    PaperJournal(path).record("fill", "paper_fill_observation", "10", {"symbol": "XYZ"})
    with pytest.raises(ValueError, match="unverified fill"):
        paper_cash_snapshot(path)


def test_unknown_event_fails_closed(tmp_path):
    path = tmp_path / "paper.sqlite3"
    PaperJournal(path).record("fund", "paper_deposit", "10", {})
    with sqlite3.connect(path) as db:
        db.execute("UPDATE paper_events SET event_type='live_order' WHERE event_id='fund'")
    with pytest.raises(ValueError, match="unknown journal event"):
        paper_cash_snapshot(path)
