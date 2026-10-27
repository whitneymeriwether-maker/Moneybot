
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
    entry_fee: float = 0.0
    exit_fee: float = 0.0


def net_trade_profit(trade):
    """Realized paper PnL after both entry and exit commissions.

    Entry/exit prices already include configured hypothetical slippage and
    spread adjustments. This does not imply executable historical fills.
    """
    return (
        (trade.exit_price - trade.entry_price) * trade.quantity
        - trade.entry_fee - trade.exit_fee
    )


def simulate_trades(
    bars,
    signals,
    starting_cash=1000.0,
    risk_per_trade=0.015,
    slippage_pct=0.001,
    max_exposure=0.5,
    max_participation=0.10,
    daily_loss_limit=0.03,
    max_drawdown_pause=0.10,
    commission_per_share=0.0,
    spread_pct=0.0,
):
    """Simulate cash-funded long trades with same-day exits.

    Cap gross notional and size entries using completed signal-minute volume.
    Verify the next minute can support the planned full fill without
    resizing the order based on future volume.
    Size for assumed adverse entry and stop-exit slippage; gaps can still
    exceed the intended risk budget.

    Treat OHLC as a hypothetical midpoint and charge half of a fixed
    assumed full bid-ask spread on each side, in addition to slippage.
    This is NOT a historical quote-based spread or executable fill model.
    Charge a fixed hypothetical commission per share on both entry and exit;
    include it in affordability, planned-stop risk, and realized paper PnL.
    Full exits require observed minute volume under the same participation\n    ceiling; insufficient liquidity invalidates the research simulation.\n    This does not model order-book depth, partial fills, or executable quotes.
    Stop new entries after the day's realized losses reach a percentage of
    initial paper capital. This cannot prevent gap losses on open positions.
    Also pause new entries when closed-trade equity falls 10% from its
    historical peak (configurable). This pause persists across sessions.
    Neither limit tracks unrealized intratrade drawdown.
    """

    if not _finite_number(starting_cash) or starting_cash <= 0:
        raise ValueError("Invalid starting cash")

    if not _finite_number(risk_per_trade) or not 0 < risk_per_trade <= 1:
        raise ValueError("Invalid risk per trade")

    if not _finite_number(slippage_pct) or not 0 <= slippage_pct < 1:
        raise ValueError("Invalid slippage")

    if not _finite_number(commission_per_share) or commission_per_share < 0:
        raise ValueError("Invalid commission per share")

    if not _finite_number(spread_pct) or not 0 <= spread_pct < 1:
        raise ValueError("Invalid assumed spread")
    if slippage_pct + spread_pct / 2 >= 1:
        raise ValueError("Combined slippage and spread must be below 100%")

    if (not _finite_number(max_exposure)
            or not 0 < max_exposure <= 1):
        raise ValueError("Invalid maximum exposure")

    if (not _finite_number(max_participation)
            or not 0 < max_participation <= 1):
        raise ValueError("Invalid maximum participation")

    if (not _finite_number(daily_loss_limit)
            or not 0 < daily_loss_limit <= 1):
        raise ValueError("Invalid daily loss limit")

    if (not _finite_number(max_drawdown_pause)
            or not 0 < max_drawdown_pause <= 1):
        raise ValueError("Invalid maximum drawdown pause")

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
        if timestamp.second or timestamp.microsecond:
            raise ValueError("Bar timestamp must be minute-aligned")
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
            or not _finite_number(price)
            or price <= 0
            for price in prices
        ):
            raise ValueError("Invalid simulated bar price")
        opening, high, low, close = prices
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("Inconsistent simulated OHLC bar")
        volume = getattr(bar, "volume", None)
        if type(volume) is not int or volume < 0 or not _finite_number(volume):
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
        if timestamp.second or timestamp.microsecond:
            raise ValueError("Signal timestamp must be minute-aligned")

        high = getattr(signal, "opening_range_high", None)
        low = getattr(signal, "opening_range_low", None)
        if (
            type(high) not in (int, float)
            or type(low) not in (int, float)
            or not _finite_number(high)
            or not _finite_number(low)
            or low <= 0
            or high <= low
        ):
            raise ValueError("Invalid opening range in signal")
        if timestamp in signals_by_time:
            raise ValueError("Duplicate signal timestamp")
        signals_by_time[timestamp] = signal

    completed = []
    cash = starting_cash
    peak_equity = starting_cash  # Closed-trade equity, not intratrade marks.
    realized_pnl_today = 0.0
    position = None
    pending = None
    previous_bar = None
    # Retain the last REGULAR-session bar for conservative liquidation.
    # Premarket/after-hours prices must not silently become exit fills.
    last_regular_bar = None

    def close_position(bar, price, reason):
        nonlocal position, cash, realized_pnl_today, peak_equity

        quantity = position["quantity"]
        # A complete exit cannot be claimed when the observed minute cannot
        # support it under the declared participation ceiling. Do not invent
        # partial fills or silently defer a stop; invalidate this simulation.
        # This check also covers forced session-end/data-end liquidations.
        if quantity > bar.volume * max_participation:
            raise ValueError("Insufficient observed exit liquidity for full paper fill")

        exit_price = price * (1 - slippage_pct - spread_pct / 2)

        # Reject arithmetic overflow rather than recording a fictitious
        # profitable fill or contaminating subsequent paper-account state.
        exit_fee = commission_per_share * quantity
        proceeds = exit_price * quantity - exit_fee
        realized_pnl = (exit_price - position["entry"]) * quantity - position["entry_fee"] - exit_fee
        if not all(isfinite(value) for value in (
            exit_fee, proceeds, realized_pnl, cash + proceeds,
            realized_pnl_today + realized_pnl,
        )):
            raise ValueError("Non-finite simulated trade arithmetic")
        if proceeds < 0:
            raise ValueError("Simulated commission exceeds exit proceeds")
        cash += proceeds
        realized_pnl_today += realized_pnl
        peak_equity = max(peak_equity, cash)

        completed.append(
            SimulatedTrade(
                entry_time=position["entry_time"],
                exit_time=bar.timestamp,
                entry_price=position["entry"],
                exit_price=exit_price,
                quantity=quantity,
                exit_reason=reason,
                entry_fee=position["entry_fee"],
                exit_fee=exit_fee,
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
                realized_pnl_today = 0.0

        # Ignore weekend prints even if a caller supplies a fabricated
        # regular-session signal. Holidays require an exchange calendar.
        if local.weekday() >= 5 or not (time(9, 30) <= clock < time(16, 0)):
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
                # Recheck the circuit breaker at fill time, not only when
                # the signal is observed. Realized PnL includes slippage.
                if (
                    realized_pnl_today <= -starting_cash * daily_loss_limit
                    or cash <= peak_equity * (1 - max_drawdown_pause)
                ):
                    pending = None
                    previous_bar = bar
                    continue

                entry = bar.open * (1 + slippage_pct + spread_pct / 2)
                if not isfinite(entry):
                    raise ValueError("Non-finite simulated trade arithmetic")

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

                # Budget for both the adverse entry fill (already in entry)
                # and exit slippage at the planned stop. Dividing only by
                # stop_distance understates risk when slippage is nonzero.
                # A gap through the stop can still exceed this estimate.
                estimated_stop_fill = (
                    entry - stop_distance
                ) * (1 - slippage_pct - spread_pct / 2)
                stop_loss_per_share = entry - estimated_stop_fill + 2 * commission_per_share
                if (
                    not isfinite(stop_loss_per_share)
                    or stop_loss_per_share <= 0
                ):
                    raise ValueError("Non-finite simulated trade arithmetic")

                # Each ratio must be finite before int() conversion:
                # tiny positive prices/stops can overflow otherwise.
                risk_shares = risk_budget / stop_loss_per_share
                affordable_shares = cash / (entry + commission_per_share)
                exposure_shares = cash * max_exposure / (entry + commission_per_share)
                # Only the completed signal minute's volume is known
                # when the next-minute market-open entry is planned.
                volume_shares = previous_bar.volume * max_participation
                if not all(isfinite(value) for value in (
                    risk_shares, affordable_shares,
                    exposure_shares, volume_shares,
                )):
                    raise ValueError("Non-finite simulated trade arithmetic")

                risk_quantity = int(risk_shares)
                affordable_quantity = int(affordable_shares)
                exposure_quantity = int(exposure_shares)
                # This caps ENTRY size only; exit liquidity remains simplified.
                volume_quantity = int(volume_shares)

                quantity = min(
                    risk_quantity,
                    affordable_quantity,
                    exposure_quantity,
                    volume_quantity,
                )

                # The entry minute's final volume is not available at
                # sizing time. Use it only as a conservative post-hoc
                # full-fill feasibility veto, never to resize a trade.
                if quantity > bar.volume * max_participation:
                    pending = None
                    previous_bar = bar
                    continue

                if quantity > 0:
                    entry_fee = commission_per_share * quantity
                    purchase_cost = entry * quantity + entry_fee
                    if not isfinite(purchase_cost) or not isfinite(entry_fee):
                        raise ValueError("Non-finite simulated trade arithmetic")

                    # Validate derived stop/target before reserving cash.
                    # Finite inputs can still overflow the 2R target, which
                    # would silently create an unreachable paper exit.
                    stop = entry - stop_distance
                    target = entry + 2 * stop_distance
                    remaining_cash = cash - purchase_cost
                    if (
                        not all(isfinite(value) for value in (
                            stop, target, remaining_cash,
                        ))
                        or stop <= 0
                        or target <= entry
                        or remaining_cash < 0
                    ):
                        raise ValueError("Non-finite simulated trade arithmetic")

                    cash = remaining_cash
                    position = {
                        "entry_time": bar.timestamp,
                        "entry": entry,
                        "quantity": quantity,
                        "entry_fee": entry_fee,
                        "stop": stop,
                        "target": target,
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
