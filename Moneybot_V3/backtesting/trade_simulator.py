
"""Historical trade simulator for Moneybot V3 research.

Paper simulation only. No broker connections or real orders.
"""

from dataclasses import dataclass
from datetime import datetime, time
from math import isfinite
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


def _finite_number(value):
    """Only finite real numeric inputs, never booleans or numeric strings."""
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class SimulatedTrade:
    entry_time: object
    exit_time: object
    entry_price: float
    exit_price: float
    quantity: int
    exit_reason: str


def simulate_trades(
    bars,
    signals,
    starting_cash=1000.0,
    risk_per_trade=0.015,
    slippage_pct=0.001,
    max_exposure=0.5,
    max_participation=0.10,
):
    """Simulate cash-funded long trades with same-day exits.

    Cap gross notional and entry size relative to observed minute volume.

    Exit fills remain simplified; this is not an execution-quality model.
    """

    if not _finite_number(starting_cash) or starting_cash <= 0:
        raise ValueError("Invalid starting cash")

    if not _finite_number(risk_per_trade) or not 0 < risk_per_trade <= 1:
        raise ValueError("Invalid risk per trade")

    if not _finite_number(slippage_pct) or not 0 <= slippage_pct < 1:
        raise ValueError("Invalid slippage")

    if (not _finite_number(max_exposure)
            or not 0 < max_exposure <= 1):
        raise ValueError("Invalid maximum exposure")

    if (not _finite_number(max_participation)
            or not 0 < max_participation <= 1):
        raise ValueError("Invalid maximum participation")

    bars = list(bars)
    # Reject malformed or nonchronological direct simulator inputs.
    # The CSV loader validates these too, but callers can pass bars directly.
    previous_timestamp = None
    for bar in bars:
        timestamp = getattr(bar, "timestamp", None)
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            raise ValueError("Bar timestamp must be timezone-aware")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("Bar timestamps must be strictly increasing")
        previous_timestamp = timestamp

        prices = (
            getattr(bar, "open", None),
            getattr(bar, "high", None),
            getattr(bar, "low", None),
            getattr(bar, "close", None),
        )
        if any(
            type(price) not in (int, float)
            or not isfinite(price)
            or price <= 0
            for price in prices
        ):
            raise ValueError("Invalid simulated bar price")
        opening, high, low, close = prices
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("Inconsistent simulated OHLC bar")
        volume = getattr(bar, "volume", None)
        if type(volume) is not int or volume < 0:
            raise ValueError("Invalid simulated bar volume")

    # Direct callers may supply externally constructed signals rather than
    # signals produced by our historical scanner. Reject invalid or ambiguous
    # stop distances before they can influence paper position sizing.
    signals_by_time = {}
    for signal in signals:
        timestamp = getattr(signal, "timestamp", None)
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or timestamp.utcoffset() is None
        ):
            raise ValueError("Signal timestamp must be timezone-aware")

        high = getattr(signal, "opening_range_high", None)
        low = getattr(signal, "opening_range_low", None)
        if (
            type(high) not in (int, float)
            or type(low) not in (int, float)
            or not isfinite(high)
            or not isfinite(low)
            or low <= 0
            or high <= low
        ):
            raise ValueError("Invalid opening range in signal")
        if timestamp in signals_by_time:
            raise ValueError("Duplicate signal timestamp")
        signals_by_time[timestamp] = signal

    completed = []
    cash = starting_cash
    position = None
    pending = None
    previous_bar = None
    # Retain the last REGULAR-session bar for conservative liquidation.
    # Premarket/after-hours prices must not silently become exit fills.
    last_regular_bar = None

    def close_position(bar, price, reason):
        nonlocal position, cash

        exit_price = price * (1 - slippage_pct)
        quantity = position["quantity"]

        # Return the proceeds from selling the shares.
        cash += exit_price * quantity

        completed.append(
            SimulatedTrade(
                entry_time=position["entry_time"],
                exit_time=bar.timestamp,
                entry_price=position["entry"],
                exit_price=exit_price,
                quantity=quantity,
                exit_reason=reason,
            )
        )

        position = None

    for bar in bars:
        local = bar.timestamp.astimezone(NEW_YORK)
        clock = local.time()
        day = local.date()

        if previous_bar is not None:
            previous_day = (
                previous_bar.timestamp
                .astimezone(NEW_YORK)
                .date()
            )

            if day != previous_day:
                if position is not None:
                    close_position(
                        last_regular_bar,
                        last_regular_bar.close,
                        "session_end",
                    )

                pending = None
                last_regular_bar = None

        if not (time(9, 30) <= clock < time(16, 0)):
            previous_bar = bar
            continue

        # A zero-volume minute contains no observable trades: it cannot
        # provide an entry, stop, target, or end-of-day fill. Retain the
        # last tradeable regular-session bar for conservative data-end exits.
        if bar.volume == 0:
            pending = None
            previous_bar = bar
            continue

        last_regular_bar = bar

        if pending is not None and position is None:
            signal_day = (
                pending.timestamp
                .astimezone(NEW_YORK)
                .date()
            )

            minutes_since_signal = (
                bar.timestamp - pending.timestamp
            ).total_seconds() / 60

            if (
                day == signal_day
                and minutes_since_signal == 1
            ):
                entry = bar.open * (1 + slippage_pct)

                stop_distance = max(
                    pending.opening_range_high
                    - pending.opening_range_low,
                    entry * 0.002,
                )

                # An extreme opening-range gap can put the proposed
                # stop at or below zero. Do not simulate such an entry.
                if stop_distance >= entry:
                    pending = None
                    previous_bar = bar
                    continue

                risk_budget = cash * risk_per_trade

                risk_quantity = int(
                    risk_budget / stop_distance
                )

                affordable_quantity = int(
                    cash / entry
                )
                exposure_quantity = int(
                    cash * max_exposure / entry
                )
                # A minute with only a handful of shares traded cannot
                # support an arbitrarily large simulated market entry.
                # This caps ENTRY size only; exits still need a fuller
                # liquidity and partial-fill model before deployment.
                volume_quantity = int(bar.volume * max_participation)

                quantity = min(
                    risk_quantity,
                    affordable_quantity,
                    exposure_quantity,
                    volume_quantity,
                )

                if quantity > 0:
                    purchase_cost = entry * quantity

                    # Reserve the cost of purchased shares.
                    cash -= purchase_cost

                    position = {
                        "entry_time": bar.timestamp,
                        "entry": entry,
                        "quantity": quantity,
                        "stop": entry - stop_distance,
                        "target": entry + 2 * stop_distance,
                    }

            pending = None

        if position is not None:
            if bar.open <= position["stop"]:
                close_position(
                    bar,
                    bar.open,
                    "stop",
                )

            elif bar.open >= position["target"]:
                close_position(
                    bar,
                    bar.open,
                    "target",
                )

            elif bar.low <= position["stop"]:
                close_position(
                    bar,
                    position["stop"],
                    "stop",
                )

            elif bar.high >= position["target"]:
                close_position(
                    bar,
                    position["target"],
                    "target",
                )

        if (
            position is not None
            and clock >= time(15, 59)
        ):
            close_position(
                bar,
                bar.close,
                "end_of_day",
            )

        if (
            position is None
            and bar.timestamp in signals_by_time
        ):
            pending = signals_by_time[bar.timestamp]

        previous_bar = bar

    if position is not None and last_regular_bar is not None:
        close_position(
            last_regular_bar,
            last_regular_bar.close,
            "data_end",
        )

    return completed
