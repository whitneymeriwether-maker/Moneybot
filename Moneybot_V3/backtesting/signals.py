
"""Historical opening-range breakout signals for V3 research."""

from dataclasses import dataclass
from datetime import datetime, time, timezone
from math import isfinite
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BreakoutSignal:
    timestamp: object
    entry_price: float
    opening_range_high: float
    opening_range_low: float
    vwap: float


def generate_breakout_signals(bars):
    """
    Find long breakout signals in chronological minute bars.

    Opening range: 9:30-9:44 AM New York time.
    First eligible signal: 9:45 AM.

    Requires all 15 opening-range minutes, plus a close above
    the opening-range high and session VWAP.

    Emits at most one signal per trading day.
    """
    signals = []
    current_day = None
    opening_high = None
    opening_low = None
    opening_minutes = set()
    cumulative_price_volume = 0.0
    cumulative_volume = 0
    signaled_today = False
    previous_utc_timestamp = None

    for bar in bars:
        # Direct scanner callers can bypass the CSV reader and simulator.
        # Never calculate a VWAP or breakout from reversed, repeated, or
        # non-minute-aligned observations: doing so leaks future information
        # or counts a traded minute more than once.
        timestamp = getattr(bar, "timestamp", None)
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            raise ValueError("Signal scanner requires timezone-aware bar timestamps")
        utc_timestamp = timestamp.astimezone(timezone.utc)
        if (
            timestamp.second or timestamp.microsecond
            or utc_timestamp.second or utc_timestamp.microsecond
        ):
            raise ValueError("Signal scanner requires UTC minute-aligned bars")
        # Compare UTC instants, not local wall-clock times: Python ignores
        # fold when comparing datetimes with the same ZoneInfo instance.
        # The repeated autumn DST hour contains distinct valid instants.
        if previous_utc_timestamp is not None and utc_timestamp <= previous_utc_timestamp:
            raise ValueError("Signal scanner requires strictly increasing bar timestamps")
        previous_utc_timestamp = utc_timestamp

        local_time = timestamp.astimezone(NEW_YORK)
        day = local_time.date()
        clock = local_time.time()

        if day != current_day:
            current_day = day
            opening_high = None
            opening_low = None
            opening_minutes = set()
            cumulative_price_volume = 0.0
            cumulative_volume = 0
            signaled_today = False

        # A weekend print is not a regular US equity trading session.
        # Exchange holidays still require a separate market calendar.
        if local_time.weekday() >= 5 or not (time(9, 30) <= clock < time(16, 0)):
            continue

        # Finite input prices can overflow when added or multiplied by
        # volume. Reject an unrepresentable VWAP rather than silently
        # suppressing a breakout when the accumulator becomes infinity.
        try:
            typical_price = (
                bar.high / 3 + bar.low / 3 + bar.close / 3
            )
            weighted_price_volume = typical_price * bar.volume
            cumulative_price_volume += weighted_price_volume
            cumulative_volume += bar.volume
            if not (
                isfinite(typical_price)
                and isfinite(weighted_price_volume)
                and isfinite(cumulative_price_volume)
            ):
                raise ValueError("Non-finite opening-range VWAP arithmetic")
        except OverflowError as error:
            raise ValueError(
                "Non-finite opening-range VWAP arithmetic"
            ) from error

        if time(9, 30) <= clock < time(9, 45):
            # A no-trade minute cannot establish a traded opening range.
            if bar.volume <= 0:
                continue
            opening_minutes.add((clock.hour, clock.minute))

            opening_high = (
                bar.high
                if opening_high is None
                else max(opening_high, bar.high)
            )
            opening_low = (
                bar.low
                if opening_low is None
                else min(opening_low, bar.low)
            )
            continue

        if (
            clock >= time(9, 45)
            and opening_high is not None
            and len(opening_minutes) == 15
            and cumulative_volume > 0
            and bar.volume > 0  # No fillable breakout without a trade.
            and not signaled_today
        ):
            try:
                vwap = cumulative_price_volume / cumulative_volume
                if not isfinite(vwap):
                    raise ValueError("Non-finite opening-range VWAP arithmetic")
            except OverflowError as error:
                raise ValueError(
                    "Non-finite opening-range VWAP arithmetic"
                ) from error

            if bar.close > opening_high and bar.close > vwap:
                signals.append(
                    BreakoutSignal(
                        timestamp=bar.timestamp,
                        entry_price=bar.close,
                        opening_range_high=opening_high,
                        opening_range_low=opening_low,
                        vwap=vwap,
                    )
                )
                signaled_today = True

    return signals
