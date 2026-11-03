"""Offline journal persistence and concurrent-writer regression tests.

Synthetic observations only: no network, broker, or paper-fill integration.
"""

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
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


def test_concurrent_cold_start_initialization_is_safe(tmp_path):
    """Multiple threads may initialize one previously nonexistent journal."""
    path = tmp_path / "cold_start.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: _write(path, minute), range(16)))
    assert results.count(True) == 1
    assert results.count(False) == 15
    assert PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.02"

def test_concurrent_identical_writers_create_only_one_row(tmp_path):
    path = tmp_path / "observations.sqlite"
    # Initialize the schema before testing concurrent record writes.
    PaperObservationJournal(path)
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
    # Initialize the schema before testing concurrent record writes.
    PaperObservationJournal(path)
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
    # Initialize the schema before testing concurrent record writes.
    PaperObservationJournal(path)
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



def test_concurrent_preclose_retry_cannot_replace_valid_observation(tmp_path):
    """A racing impossible receipt cannot win or mutate an immutable minute."""
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    PaperObservationJournal(path)

    def write_with_receipt(delay):
        return PaperObservationJournal(path).record(
            feed="alpaca-iex", symbol="SPY", minute=minute,
            received_at=minute + timedelta(seconds=delay),
            open="500.01", high="500.03", low="500.00",
            close="500.02", volume=100,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        good = pool.submit(write_with_receipt, 70)
        bad = pool.submit(write_with_receipt, 59)
        assert good.result() is True
        with pytest.raises(ValueError, match="receipt precedes minute completion"):
            bad.result()

    assert write_with_receipt(80) is False
    latest = PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=90),
    )
    assert latest["received_utc"] == (
        minute + timedelta(seconds=70)
    ).isoformat(timespec="microseconds")


def test_concurrent_stale_new_minute_cannot_displace_fresh_minute(tmp_path):
    """Stale first inserts must fail even when a fresh minute is racing."""
    path = tmp_path / "observations.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    PaperObservationJournal(path)

    def write_with_receipt(delay):
        return PaperObservationJournal(path).record(
            feed="alpaca-iex", symbol="SPY", minute=minute,
            received_at=minute + timedelta(seconds=delay),
            open="500.01", high="500.03", low="500.00",
            close="500.02", volume=100,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        fresh = pool.submit(write_with_receipt, 70)
        stale = pool.submit(write_with_receipt, 190)
        assert fresh.result() is True
        # If stale arrives after the fresh insert, it is an identical retry;
        # if it arrives first, it must be rejected. Neither can rewrite data.
        try:
            assert stale.result() is False
        except ValueError as error:
            assert "Incomplete or stale observation" in str(error)

    latest = PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=90),
    )
    assert latest["received_utc"] == (
        minute + timedelta(seconds=70)
    ).isoformat(timespec="microseconds")


def test_separate_processes_share_initialized_journal_safely(tmp_path):
    """Independent Python processes must serialize writes to one SQLite key."""
    path = tmp_path / "multiprocess.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    # Provision first: this isolates cross-process writes from the still
    # unverified cross-process cold-start initialization race.
    PaperObservationJournal(path)
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_write_process, [(str(path), minute)] * 8))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.02"


def _write_process(args):
    path, minute = args
    return _write(path, minute)


def test_separate_processes_reject_conflicting_replay(tmp_path):
    """A competing process cannot silently replace an immutable observation."""
    path = tmp_path / "multiprocess_conflict.sqlite"
    minute = datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)
    PaperObservationJournal(path)
    # Commit the valid row first, then race independent conflicting replays.
    assert _write(path, minute) is True
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_write_process_conflict, (str(path), minute))
                   for _ in range(8)]
        for future in futures:
            with pytest.raises(ValueError, match="Conflicting observation replay"):
                future.result()
    assert PaperObservationJournal(path).audited_latest(
        feed="alpaca-iex", symbol="SPY",
        as_of=minute + timedelta(seconds=80),
    )["close"] == "500.02"


def _write_process_conflict(args):
    path, minute = args
    return _write(path, minute, close="500.03")
