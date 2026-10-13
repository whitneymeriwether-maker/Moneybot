"""Additional local correctness checks (not a substitute for Neon integration tests)."""
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
from agent.engine import PaperEngine


def bars():
    idx = pd.date_range('2026-10-12 09:30', periods=12, freq='5min', tz='America/New_York')
    return pd.DataFrame({'open': 100., 'high': 100.2, 'low': 99.8, 'close': 100., 'volume': 1000}, index=idx)


def test_unsorted_data_rejected(tmp_path):
    engine = PaperEngine(tmp_path / 'state.db')
    with pytest.raises(ValueError, match='chronologically'):
        engine.process('TEST', bars().iloc[::-1])


def test_concurrent_bootstrap_has_one_winner(tmp_path):
    path = tmp_path / 'state.db'
    PaperEngine(path)
    def attempt(_):
        return PaperEngine(path).bootstrap('TEST', bars())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count(True) == 1
    assert results.count(False) == 3


def test_replay_after_concurrent_bootstrap(tmp_path):
    path = tmp_path / 'state.db'
    engine = PaperEngine(path)
    engine.bootstrap('TEST', bars())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: PaperEngine(path).process('TEST', bars()), range(2)))
    assert engine.snapshot()[2].empty
