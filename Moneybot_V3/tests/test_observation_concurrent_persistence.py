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


def test_concurrent_distinct_symbols_remain_independent(tmp_path):
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    symbols = ("SPY", "QQQ", "IWM", "DIA")

    def write_symbol(symbol):
        return PaperObservationJournal(path).record(
            feed="alpaca-iex", symbol=symbol, minute=minute,
            received_at=minute + timedelta(seconds=70),
            open="500.01", high="500.03", low="500.00",
            close="500.02", volume=100,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(write_symbol, symbols)) == [True] * len(symbols)
    for symbol in symbols:
        latest = PaperObservationJournal(path).audited_latest(
            feed="alpaca-iex", symbol=symbol,
            as_of=minute + timedelta(seconds=80),
        )
        assert latest["symbol"] == symbol
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0] == len(symbols)


def test_concurrent_unsupported_feeds_fail_without_persisting(tmp_path):
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    PaperObservationJournal(path)
    feeds = ("research-synthetic", "unknown-provider")

    def write_feed(feed):
        return PaperObservationJournal(path).record(
            feed=feed, symbol="SPY", minute=minute,
            received_at=minute + timedelta(seconds=70),
            open="500.01", high="500.03", low="500.00",
            close="500.02", volume=100,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write_feed, feed) for feed in feeds]
        for future in futures:
            with pytest.raises(ValueError, match="Unsupported declared research feed"):
                future.result()
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0] == 0


def test_concurrent_supported_and_unsupported_feeds_are_isolated(tmp_path):
    """A rejected provider cannot suppress a valid independent observation."""
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    PaperObservationJournal(path)

    def write_feed(feed):
        return PaperObservationJournal(path).record(
            feed=feed, symbol="SPY", minute=minute,
            received_at=minute + timedelta(seconds=70),
            open="500.01", high="500.03", low="500.00",
            close="500.02", volume=100,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(write_feed, "alpaca-iex")
        rejected = pool.submit(write_feed, "unknown-provider")
        assert accepted.result() is True
        with pytest.raises(ValueError, match="Unsupported declared research feed"):
            rejected.result()

    latest = PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )
    assert latest["close"] == "500.02"
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_observations").fetchone()[0] == 1
