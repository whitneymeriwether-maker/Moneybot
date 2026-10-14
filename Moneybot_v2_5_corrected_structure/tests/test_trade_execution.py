
"""Tests for simulated trade execution and risk controls.

Uses artificial prices and temporary databases only.
No Alpaca orders or changes to the virtual account.
"""

import pandas as pd

from agent.engine import PaperEngine


def make_bars():
    """Create a complete trading session of five-minute candles."""
    idx = pd.date_range(
        "2026-10-12 09:30",
        periods=78,
        freq="5min",
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [101.0] * len(idx),
            "low": [99.0] * len(idx),
            "close": [100.0] * len(idx),
            "volume": [1000] * len(idx),
        },
        index=idx,
    )


def force_buy_signal(monkeypatch):
    """Force a strategy signal inside the test only."""
    monkeypatch.setattr(
        "agent.engine.find_signal",
        lambda data: {"decision": "WATCH"},
    )


def test_simulated_entry_respects_cash_and_exposure(tmp_path, monkeypatch):
    force_buy_signal(monkeypatch)
    engine = PaperEngine(tmp_path / "entry.sqlite3")

    # Process only the morning so the position remains open.
    engine.process("TEST", make_bars().iloc[:30])

    cash, positions, events = engine.snapshot()
    entries = events[events["kind"] == "ENTRY"]

    assert len(entries) == 1
    assert len(positions) == 1
    assert 0 <= cash <= 1000

    symbol, entry_price, qty, stop, target, entry_ts = positions[0]

    assert symbol == "TEST"
    assert float(entry_price) == 100.0
    assert qty >= 1
    assert qty * float(entry_price) <= 250.0


def test_simulated_exit_and_replay_protection(tmp_path, monkeypatch):
    force_buy_signal(monkeypatch)
    engine = PaperEngine(tmp_path / "exit.sqlite3")

    bars = make_bars()
    engine.process("TEST", bars)

    first_cash, first_positions, first_events = engine.snapshot()

    assert (first_events["kind"] == "ENTRY").sum() == 1
    assert (first_events["kind"] == "EXIT").sum() == 1
    assert first_positions == []

    engine.process("TEST", bars)
    second_cash, second_positions, second_events = engine.snapshot()

    assert second_cash == first_cash
    assert second_positions == first_positions
    assert len(second_events) == len(first_events)


def test_risk_limit_prevents_oversized_purchase(tmp_path, monkeypatch):
    force_buy_signal(monkeypatch)

    engine = PaperEngine(
        tmp_path / "risk.sqlite3",
        starting_cash=1000,
        exposure_pct=0.01,
    )
    engine.process("TEST", make_bars())

    cash, positions, events = engine.snapshot()

    assert cash == 1000
    assert positions == []
    assert events.empty
