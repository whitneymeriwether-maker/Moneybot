"""Offline journal persistence and concurrent-writer regression tests.

Synthetic observations only: no network, broker, or paper-fill integration.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from v3_observation_journal import PaperObservationJournal


def _write(path, minute, *, close="500.02"):
    journal = PaperObservationJournal(path)
    return journal.record(
        feed="alpaca-iex", symbol="SPY", minute=minute,
        received_at=minute + timedelta(seconds=70),
        open="500.01", high="500.03", low="500.00", close=close,
        volume=100,
    )


def test_reopen_preserves_immutable_observation(tmp_path):
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    assert _write(path, minute) is True
    assert _write(path, minute) is False
    reopened = PaperObservationJournal(path)
    assert reopened.audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.02"
    with pytest.raises(ValueError, match="Conflicting"):
        _write(path, minute, close="500.03")


def test_concurrent_identical_writers_create_only_one_row(tmp_path):
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _write(path, minute), range(12)))
    assert results.count(True) == 1
    assert results.count(False) == 11
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0] == 1


def test_concurrent_conflicting_writers_cannot_overwrite(tmp_path):
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_write, path, minute, close=value)
                   for value in ("500.02", "500.03")]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except ValueError as error:
                outcomes.append(str(error))
    assert outcomes.count(True) == 1
    assert sum("Conflicting observation replay" in str(x) for x in outcomes) == 1
