"""Fail-closed exit liquidity checks for offline V3 paper research only."""

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.trade_simulator import simulate_trades


NY = ZoneInfo("America/New_York")


def bar(minute, opening=101, high=102, low=100, close=101, volume=1000, day=12):
    return SimpleNamespace(
        timestamp=datetime(2026, 10, day, 9, 45, tzinfo=NY)
        + timedelta(minutes=minute),
        open=opening, high=high, low=low, close=close, volume=volume,
    )


def signal(first_bar):
    return SimpleNamespace(
        timestamp=first_bar.timestamp,
        opening_range_high=101.0,
        opening_range_low=99.0,
    )


@pytest.mark.parametrize("exit_bar", [
    lambda: bar(2, opening=106, high=107, low=105, close=106, volume=20),
    lambda: bar(2, opening=98, high=99, low=97, close=98, volume=20),
])
def test_target_or_stop_cannot_claim_full_exit_without_liquidity(exit_bar):
    bars = [bar(0), bar(1), exit_bar()]
    with pytest.raises(ValueError, match="Insufficient observed exit liquidity"):
        simulate_trades(bars, [signal(bars[0])], slippage_pct=0)


def test_data_end_cannot_claim_unfillable_liquidation():
    bars = [bar(0), bar(1), bar(2, volume=20)]
    with pytest.raises(ValueError, match="Insufficient observed exit liquidity"):
        simulate_trades(bars, [signal(bars[0])], slippage_pct=0)


def test_session_rollover_cannot_claim_unfillable_liquidation():
    bars = [bar(0), bar(1), bar(2, volume=20), bar(0, day=13)]
    with pytest.raises(ValueError, match="Insufficient observed exit liquidity"):
        simulate_trades(bars, [signal(bars[0])], slippage_pct=0)


def test_exit_at_exact_participation_limit_is_permitted():
    bars = [bar(0), bar(1), bar(2, opening=106, high=107, low=105,
                                  close=106, volume=40)]
    trades = simulate_trades(bars, [signal(bars[0])], slippage_pct=0)
    assert len(trades) == 1
    assert trades[0].quantity == 4
    assert trades[0].exit_reason == "target"


def test_tighter_participation_limit_also_applies_to_exits():
    bars = [bar(0), bar(1), bar(2, opening=106, high=107, low=105,
                                  close=106, volume=100)]
    with pytest.raises(ValueError, match="Insufficient observed exit liquidity"):
        simulate_trades(
            bars, [signal(bars[0])], slippage_pct=0,
            max_participation=0.01,
        )
