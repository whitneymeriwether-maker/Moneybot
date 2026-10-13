from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import pytest
from worker_once import eligible_time, recent_complete_bars, run_once

ET = ZoneInfo('America/New_York')

def test_only_regular_weekday_window():
    assert eligible_time(datetime(2026, 10, 13, 10, 0, tzinfo=ET))
    assert not eligible_time(datetime(2026, 10, 17, 10, 0, tzinfo=ET))
    assert not eligible_time(datetime(2026, 10, 13, 16, 5, tzinfo=ET))

def test_stale_bars_fail_closed():
    now = datetime(2026, 10, 13, 11, 0, tzinfo=ET)
    bars = pd.DataFrame({'close':[100]}, index=pd.DatetimeIndex([datetime(2026, 10, 13, 10, 0, tzinfo=ET)]))
    with pytest.raises(RuntimeError, match='stale'):
        recent_complete_bars(bars, now)

def test_no_db_url_fails_closed(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        run_once(datetime(2026, 10, 13, 11, 0, tzinfo=ET))

def test_outside_hours_skips_without_creating_engine():
    assert run_once(datetime(2026, 10, 17, 11, 0, tzinfo=ET)) == 0
