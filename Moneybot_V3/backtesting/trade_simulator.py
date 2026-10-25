
"""Historical trade simulator for Moneybot V3 research.

Paper simulation only. No broker connections or real orders.
"""

from dataclasses import dataclass
from datetime import time
from math import isfinite
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


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
):
    """Simulate cash-funded long trades with same-day exits."""

    if not isfinite(starting_cash) or starting_cash <= 0:
        raise ValueError("Invalid starting cash")

    if not isfinite(risk_per_trade) or not 0 < risk_per_trade <= 1:
        raise ValueError("Invalid risk per trade")

    if not isfinite(slippage_pct) or not 0 <= slippage_pct < 1:
        raise ValueError("Invalid slippage")

    bars = list(bars)
    signals_by_time = {
        signal.timestamp: signal for signal in signals
    }

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

                risk_budget = cash * risk_per_trade

                risk_quantity = int(
                    risk_budget / stop_distance
                )

                affordable_quantity = int(
                    cash / entry
                )

                quantity = min(
                    risk_quantity,
                    affordable_quantity,
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
