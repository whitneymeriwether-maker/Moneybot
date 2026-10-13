"""First-pass backtest helpers. Feed in a DataFrame of historical 5-minute bars."""
import pandas as pd
from agent.strategy import build_features

def backtest_opening_range(bars: pd.DataFrame, starting_equity=1000.0,
                           risk_per_trade=0.005, max_exposure=0.25,
                           stop_atr=1.0, target_r=2.0):
    """
    Simple conservative single-symbol, one-position-at-a-time backtest.
    Signals on completed bars; assumes entry at next bar open.
    If stop and target are both touched within the same bar, stop is assumed first.
    This function is an initial validation scaffold, not a production-grade simulator.
    """
    df = build_features(bars)
    if df.empty:
        return pd.DataFrame(), {"trades": 0, "ending_equity": starting_equity}
    equity = float(starting_equity)
    trades = []
    in_trade = False
    position = None
    dates = df["session_date"].tolist()

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        bar = df.iloc[i]
        day_changed = dates[i] != dates[i - 1]

        if in_trade:
            exit_price, exit_reason = None, None
            if day_changed:
                exit_price, exit_reason = float(prev["close"]), "end_of_day"
            else:
                if float(bar["low"]) <= position["stop"]:
                    exit_price, exit_reason = position["stop"], "stop"
                elif float(bar["high"]) >= position["target"]:
                    exit_price, exit_reason = position["target"], "target"
                elif str(bar["clock"]) >= "15:55":
                    exit_price, exit_reason = float(bar["close"]), "end_of_day"
            if exit_price is not None:
                pnl = (exit_price - position["entry"]) * position["qty"]
                equity += pnl
                trades.append({**position, "exit_time": df.index[i].isoformat(),
                               "exit_price": exit_price, "exit_reason": exit_reason,
                               "pnl": pnl, "equity_after": equity})
                in_trade, position = False, None

        if not in_trade and not day_changed:
            # Only enter after a completed bar has generated the signal; fill at next bar open.
            sig = prev
            if str(sig["clock"]) < "09:45" or str(sig["clock"]) >= "15:50":
                continue
            needed = ["opening_range_high", "vwap", "atr14", "relative_volume", "ema9", "ema20"]
            if any(pd.isna(sig.get(k)) for k in needed):
                continue
            passed = (
                float(sig["close"]) > float(sig["opening_range_high"])
                and float(sig["close"]) > float(sig["vwap"])
                and float(sig["relative_volume"]) >= 1.5
                and float(sig["ema9"]) > float(sig["ema20"])
            )
            if not passed:
                continue
            entry = float(bar["open"])
            stop_distance = max(float(sig["atr14"]) * stop_atr, entry * 0.002)
            stop = entry - stop_distance
            target = entry + stop_distance * target_r
            risk_dollars = equity * risk_per_trade
            qty_by_risk = int(risk_dollars / stop_distance)
            qty_by_exposure = int(equity * max_exposure / entry)
            qty = min(qty_by_risk, qty_by_exposure)
            if qty < 1:
                continue
            position = {
                "symbol": str(bar.get("symbol", "")),
                "entry_time": df.index[i].isoformat(),
                "entry": entry, "stop": stop, "target": target,
                "qty": qty, "risk_dollars_planned": qty * stop_distance,
            }
            in_trade = True

    summary = {
        "trades": len(trades),
        "starting_equity": starting_equity,
        "ending_equity": round(equity, 2),
        "net_pnl": round(equity - starting_equity, 2),
        "win_rate_pct": round(100 * sum(t["pnl"] > 0 for t in trades) / len(trades), 2) if trades else 0.0,
        "profit_factor": round(sum(t["pnl"] for t in trades if t["pnl"] > 0) / abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 3)
            if any(t["pnl"] < 0 for t in trades) else None,
    }
    return pd.DataFrame(trades), summary
