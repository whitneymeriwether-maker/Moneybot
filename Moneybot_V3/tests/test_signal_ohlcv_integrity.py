"""Offline regression checks for direct scanner OHLCV integrity.

No provider calls, broker connections, or order submission.
"""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from backtesting.historical_data import MAX_EXACT_SHARE_VOLUME, PriceBar
from backtesting.signals import generate_breakout_signals


def bar(**changes):
    original = PriceBar(
        timestamp=datetime(2026, 10, 12, 13, 30, tzinfo=timezone.utc),
        open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
    )
    return replace(original, **changes)


@pytest.mark.parametrize("field,value", [
    ("open", 0),
    ("high", -1),
    ("low", float("nan")),
    ("close", float("inf")),
    ("open", True),
    ("close", "100"),
    ("high", 10 ** 400),
])
def test_rejects_invalid_direct_scanner_prices(field, value):
    with pytest.raises(ValueError, match="Invalid signal bar price"):
        generate_breakout_signals([bar(**{field: value})])


@pytest.mark.parametrize("changes", [
    {"high": 99.0},
    {"low": 101.0},
    {"open": 102.0},
    {"close": 102.0},
])
def test_rejects_inconsistent_direct_scanner_ohlc(changes):
    with pytest.raises(ValueError, match="Inconsistent signal OHLC"):
        generate_breakout_signals([bar(**changes)])


@pytest.mark.parametrize("volume", [
    -1, True, 1000.0, "1000", None, MAX_EXACT_SHARE_VOLUME + 1,
])
def test_rejects_malformed_or_unrepresentable_share_volume(volume):
    with pytest.raises(ValueError, match="Invalid signal bar volume"):
        generate_breakout_signals([bar(volume=volume)])


def test_accepts_zero_volume_and_maximum_exact_share_count():
    # No-trade bars remain permitted in exploratory scanning; neither a
    # zero-volume opening minute nor one isolated traded minute is a signal.
    assert generate_breakout_signals([
        bar(volume=0),
        bar(timestamp=datetime(2026, 10, 12, 13, 31, tzinfo=timezone.utc),
            volume=MAX_EXACT_SHARE_VOLUME),
    ]) == []


def test_rejects_invalid_after_hours_bar_before_later_session():
    # Do not allow a malformed observation to disappear when a caller
    # passes a full tape through the scanner's session filter.
    with pytest.raises(ValueError, match="Invalid signal bar volume"):
        generate_breakout_signals([
            bar(timestamp=datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc),
                volume=-1),
            bar(),
        ])
