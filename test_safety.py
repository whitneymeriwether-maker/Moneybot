"""Safety regression tests for paper-only execution."""
import pandas as pd
from agent.engine import PaperEngine


def flat_bars(day='2026-10-12'):
    idx = pd.date_range(f'{day} 09:30', periods=78, freq='5min', tz='America/New_York')
    return pd.DataFrame({'open':100., 'high':100.2, 'low':99.8, 'close':100., 'volume':1000}, index=idx)


def test_replay_after_restart_does_not_duplicate_events(tmp_path):
    path = tmp_path / 'state.sqlite3'
    bars = flat_bars()
    PaperEngine(path).process('TEST', bars)
    before = PaperEngine(path).snapshot()
    PaperEngine(path).process('TEST', bars)
    after = PaperEngine(path).snapshot()
    assert before[0] == after[0]
    assert len(before[2]) == len(after[2])


def test_bootstrap_skips_old_bars(tmp_path):
    engine = PaperEngine(tmp_path / 'state.sqlite3')
    bars = flat_bars()
    assert engine.bootstrap('TEST', bars)
    assert not engine.bootstrap('TEST', bars)
    engine.process('TEST', bars)
    assert engine.snapshot()[2].empty


def test_rejects_duplicate_bars(tmp_path):
    engine = PaperEngine(tmp_path / 'state.sqlite3')
    bars = flat_bars()
    duplicated = pd.concat([bars, bars.iloc[[-1]]]).sort_index()
    try:
        engine.process('TEST', duplicated)
    except ValueError as exc:
        assert 'duplicate' in str(exc).lower()
    else:
        raise AssertionError('Duplicate bars were accepted')
