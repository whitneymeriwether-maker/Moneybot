"""Whole-share precision checks for direct offline simulator inputs.

No broker connections, market-data calls, or order submission.
"""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.trade_simulator import simulate_trades


MAX_SAFE = (1 << 53) - 1
NY = ZoneInfo("America/New_York")


def make_bar(minute, volume):
    return SimpleNamespace(
        timestamp=datetime(2026, 10, 12, 9, 45, tzinfo=NY)
        + timedelta(minutes=minute),
        open=100.0, high=101.0, low=99.0, close=100.0,
        volume=volume,
    )


@pytest.mark.parametrize("volume", [MAX_SAFE + 1, MAX_SAFE + 2, 10 ** 100])
@pytest.mark.parametrize("minute", [0, 1])
def test_direct_simulator_rejects_inexact_share_counts(volume, minute):
    bars = [make_bar(0, 1000), make_bar(1, 1000)]
    bars[minute].volume = volume
    with pytest.raises(ValueError, match="Invalid simulated bar volume"):
        simulate_trades(bars, [])


def test_direct_simulator_accepts_largest_exact_share_count():
    assert simulate_trades([make_bar(0, MAX_SAFE)], []) == []


def test_direct_simulator_preserves_zero_volume_non_signal_bar():
    # Sparse exploratory tapes can have zero-volume bars. Such a bar
    # cannot form a breakout signal or execute a hypothetical fill.
    assert simulate_trades([make_bar(0, 0)], []) == []
