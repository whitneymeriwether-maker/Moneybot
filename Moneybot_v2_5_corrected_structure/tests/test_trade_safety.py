
"""Additional safety tests for Moneybot's paper-trading engine."""

import pandas as pd
import pytest

from agent.engine import PaperEngine


def make_bars():
    """Create artificial five-minute market data."""
    index = pd.date_range(
        "2026-10-12 09:30",
        periods=78,
        freq="5min",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.0,
            "volume": 1000,
        },
        index=index,
    )


def test_no_trades_on_flat_market(tmp_path):
    engine = PaperEngine(tmp_path / "flat.sqlite3")
    engine.process("TEST", make_bars())

    cash, positions, events = engine.snapshot()

    assert cash == 1000.0
    assert positions == []
    assert events.empty


def test_replaying_bars_does_not_change_account(tmp_path):
    engine = PaperEngine(tmp_path / "replay.sqlite3")
    bars = make_bars()

    engine.process("TEST", bars)
    before = engine.snapshot()

    engine.process("TEST", bars)
    after = engine.snapshot()

    assert before[0] == after[0]
    assert before[1] == after[1]
    pd.testing.assert_frame_equal(before[2], after[2])


def test_rejects_unsorted_market_data(tmp_path):
    engine = PaperEngine(tmp_path / "unsorted.sqlite3")
    bars = make_bars().iloc[::-1]

    with pytest.raises(ValueError, match="sorted"):
        engine.process("TEST", bars)
