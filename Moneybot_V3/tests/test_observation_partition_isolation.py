"""Research journal partition-isolation regression coverage.

These tests use synthetic data only; they do not authenticate a feed or
authorize simulated or real orders.
"""

from datetime import datetime, timedelta, timezone

import pytest

from v3_observation_journal import PaperObservationJournal


def _record(journal, symbol, minute, *, close="500.02", receipt_seconds=65):
    return journal.record(
        feed="alpaca-iex", symbol=symbol, minute=minute,
        received_at=minute + timedelta(seconds=receipt_seconds),
        open="500.01", high="500.03", low="500.00", close=close,
        volume=100,
    )


def test_same_minute_is_independent_across_symbols(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    assert _record(journal, "SPY", minute)
    assert _record(journal, "QQQ", minute, close="500.03")
    assert _record(journal, "SPY", minute) is False
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="QQQ",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.03"
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.02"


def test_out_of_order_rejection_is_partition_local(tmp_path):
    journal = PaperObservationJournal(tmp_path / "observations.sqlite")
    first = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    second = first + timedelta(minutes=1)
    assert _record(journal, "SPY", second)
    with pytest.raises(ValueError, match="Out-of-order"):
        _record(journal, "SPY", first)
    assert _record(journal, "QQQ", first)
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="QQQ",
        as_of=first + timedelta(seconds=80),
    )["minute_utc"] == first.isoformat(timespec="microseconds")


def test_corruption_in_other_symbol_does_not_contaminate_audit(tmp_path):
    import sqlite3

    path = tmp_path / "observations.sqlite"
    journal = PaperObservationJournal(path)
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    assert _record(journal, "SPY", minute)
    assert _record(journal, "QQQ", minute)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE paper_observations SET high=? WHERE symbol=?",
            ("0.01", "QQQ"),
        )
    assert journal.audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["symbol"] == "SPY"
    with pytest.raises(ValueError, match="Corrupt"):
        journal.audited_latest(
            feed="alpaca-iex", symbol="QQQ",
            as_of=minute + timedelta(seconds=80),
        )
