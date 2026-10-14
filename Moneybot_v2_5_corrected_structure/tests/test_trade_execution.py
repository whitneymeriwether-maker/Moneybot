
"""Tests for simulated trade execution and risk controls.

Uses a temporary database and artificial prices.
No Alpaca orders or real account activity.
"""

import pandas as pd
import pytest

from agent.engine import PaperEngine


def make_bars():
    idx = pd.date_range(
        "2026-10-12 09:30",
        periods=30,
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
    """Replace the strategy signal for a controlled test."""
    monkeypatch.setattr(
        "agent.engine.find_signal",
        lambda data: {"decision": "WATCH"},
    )


def test_simulated_entry_respects_cash_and_exposure(tmp_path, monkeypatch):
    force_buy_signal(monkeypatch)
    engine = PaperEngine(tmp_path / "entry.sqlite3")
    engine.process("TEST", make_bars())

    cash, positions, events = engine.snapshot()
    entries = events[events["kind"] == "ENTRY"]

    assert len(entries) == 1
    assert len(positions) == 1
    assert 0 <= cash <= 1000
    assert float(positions[0][0]) == 100.0
    assert positions[0][1] >= 1
    assert positions[0][1] * float(positions[0][0]) <= 250.0


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
