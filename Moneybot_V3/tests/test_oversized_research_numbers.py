"""Regression tests: reject huge integers before implicit float conversion.

Offline historical research only; no network, broker, or order submission.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.historical_data import PriceBar
from backtesting.trade_simulator import simulate_trades
from backtesting.walk_forward import (
    build_research_folds,
    evaluate_fixed_baseline_folds,
)


STAMP = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("America/New_York"))
HUGE = 10 ** 400


def bar(**changes):
    fields = dict(
        timestamp=STAMP, open=100.0, high=101.0,
        low=99.0, close=100.0, volume=1000,
    )
    fields.update(changes)
    return PriceBar(**fields)


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_simulator_rejects_oversized_bar_prices_as_validation_error(field):
    with pytest.raises(ValueError, match="Invalid simulated bar price"):
        simulate_trades([bar(**{field: HUGE})], [])


@pytest.mark.parametrize("field", ["opening_range_high", "opening_range_low"])
def test_simulator_rejects_oversized_signal_prices_as_validation_error(field):
    signal = SimpleNamespace(
        timestamp=STAMP, opening_range_high=101.0, opening_range_low=99.0,
    )
    setattr(signal, field, HUGE)
    with pytest.raises(ValueError, match="Invalid opening range in signal"):
        simulate_trades([bar()], [signal])


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_fold_builder_rejects_oversized_bar_prices_as_validation_error(field):
    with pytest.raises(ValueError, match="Invalid research OHLC price"):
        build_research_folds(
            [bar(**{field: HUGE})], train_sessions=1, test_sessions=1,
        )


def test_fold_builder_rejects_oversized_volume_as_validation_error():
    with pytest.raises(ValueError, match="traded minute volumes"):
        build_research_folds(
            [bar(volume=HUGE)], train_sessions=1, test_sessions=1,
        )


def test_fold_evaluator_rejects_oversized_starting_cash_as_validation_error():
    with pytest.raises(ValueError, match="Invalid starting cash"):
        evaluate_fixed_baseline_folds([object()], starting_cash=HUGE)
