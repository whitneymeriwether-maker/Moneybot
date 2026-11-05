"""Cross-process cold-start regression for the durable paper ledger (Linux CI)."""

import multiprocessing
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_ledger import PaperLedger


def _initialize(path, gate, results):
    try:
        if not gate.wait(timeout=15):
            raise TimeoutError("Initialization gate timed out")
        results.put(("ok", PaperLedger(path).snapshot()))
    except BaseException as error:
        results.put(("error", repr(error)))


def test_simultaneous_first_initialization_across_processes(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Event()
    results = ctx.Queue()
    workers = [
        ctx.Process(target=_initialize, args=(str(path), gate, results))
        for _ in range(6)
    ]
    try:
        for worker in workers:
            worker.start()
        gate.set()
        outcomes = [results.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
        assert all(worker.exitcode == 0 for worker in workers)
        assert all(kind == "ok" for kind, _ in outcomes), outcomes
        snapshots = [payload for _, payload in outcomes]
        assert all(snapshot == snapshots[0] for snapshot in snapshots)
        assert snapshots[0]["starting_cash"] == "1000.00"
        assert snapshots[0]["fill_count"] == 0
        assert PaperLedger(path).snapshot() == snapshots[0]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)


@pytest.mark.parametrize("kind", ["empty", "unrelated"])
def test_preexisting_database_still_fails_closed_with_init_lock(tmp_path, kind):
    import sqlite3

    path = tmp_path / "existing.sqlite3"
    if kind == "empty":
        path.touch()
    else:
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError, match="Existing SQLite file has no paper ledger schema"):
        PaperLedger(path)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='paper_account'"
        ).fetchone() is None
