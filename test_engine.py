import pandas as pd
from agent.engine import PaperEngine

def test_empty_and_idempotent(tmp_path):
    engine = PaperEngine(tmp_path/'test.sqlite3')
    idx = pd.date_range('2026-10-12 09:30', periods=30, freq='5min', tz='America/New_York')
    bars = pd.DataFrame({'open':100.,'high':100.2,'low':99.8,'close':100.,'volume':1000},index=idx)
    engine.process('TEST', bars)
    first = engine.snapshot()
    engine.process('TEST', bars)
    second = engine.snapshot()
    assert first[0] == second[0] == 1000
    assert len(first[2]) == len(second[2])
