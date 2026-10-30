"""Direct gap validation must not accept reversed, repeated, or unaligned bars.

These synthetic observations never touch market providers or brokers.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from backtesting.pipeline import validate_regular_session_gaps


def _bars(*timestamps):
    return [
        SimpleNamespace(timestamp=datetime.fromisoformat(stamp))
        for stamp in timestamps
    ]


@pytest.mark.parametrize("tolerance", [1, 2, 390])
def test_reversed_regular_minutes_fail_even_when_gaps_are_relaxed(tolerance):
    bars = _bars(
        "2026-10-12T09:32:00-04:00",
        "2026-10-12T09:31:00-04:00",
    )
    with pytest.raises(ValueError, match="strictly chronological"):
        validate_regular_session_gaps(bars, max_gap_minutes=tolerance)


def test_duplicate_regular_minute_fails():
    bars = _bars(
        "2026-10-12T09:30:00-04:00",
        "2026-10-12T09:30:00-04:00",
    )
    with pytest.raises(ValueError, match="strictly chronological"):
        validate_regular_session_gaps(bars)


def test_equivalent_instant_in_different_offsets_is_still_duplicate():
    bars = _bars(
        "2026-10-12T09:30:00-04:00",
        "2026-10-12T13:30:00+00:00",
    )
    with pytest.raises(ValueError, match="strictly chronological"):
        validate_regular_session_gaps(bars)


def test_valid_chronology_with_mixed_offsets_is_accepted():
    bars = _bars(
        "2026-10-12T09:30:00-04:00",
        "2026-10-12T13:31:00+00:00",
    )
    validate_regular_session_gaps(bars)


def test_reversed_extended_hours_cannot_hide_invalid_tape():
    bars = _bars(
        "2026-10-12T08:30:00-04:00",
        "2026-10-12T08:29:00-04:00",
    )
    with pytest.raises(ValueError, match="strictly chronological"):
        validate_regular_session_gaps(bars)


def test_nonminute_aligned_direct_bar_is_rejected():
    bars = _bars("2026-10-12T09:30:30-04:00")
    with pytest.raises(ValueError, match="UTC minute-aligned"):
        validate_regular_session_gaps(bars)


def test_naive_direct_bar_is_rejected():
    bars = _bars("2026-10-12T09:30:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_regular_session_gaps(bars)
