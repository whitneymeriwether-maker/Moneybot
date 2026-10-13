import numpy as np
import pandas as pd

def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Calculate simple intraday features from chronological 5-minute OHLCV bars."""
    if bars.empty:
        return bars.copy()
    df = bars.copy().sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].astype(float).clip(lower=0)
    df["vwap"] = (typical * vol).groupby(df.index.date).cumsum() / vol.groupby(df.index.date).cumsum().replace(0, np.nan)
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=3).mean()

    local_time = df.index.tz_convert("America/New_York") if df.index.tz is not None else df.index
    df["session_date"] = pd.Index(local_time.date)
    df["clock"] = pd.Index(local_time.strftime("%H:%M"))
    # Opening range uses bars timestamped 09:30, 09:35, and 09:40.
    df["opening_range_high"] = np.nan
    df["opening_range_low"] = np.nan
    for day in pd.unique(df["session_date"]):
        mask = df["session_date"] == day
        opening = mask & df["clock"].isin(["09:30", "09:35", "09:40"])
        if opening.any():
            hi = df.loc[opening, "high"].max()
            lo = df.loc[opening, "low"].min()
            df.loc[mask, "opening_range_high"] = hi
            df.loc[mask, "opening_range_low"] = lo
    df["volume_sma20"] = df["volume"].rolling(20, min_periods=5).mean()
    df["relative_volume"] = df["volume"] / df["volume_sma20"].replace(0, np.nan)
    df["return_3bar_pct"] = df["close"].pct_change(3) * 100
    return df

def find_signal(features: pd.DataFrame) -> dict:
    """Evaluate the latest completed bar. Returns WATCH or NO TRADE, never an order."""
    if features.empty:
        return {"decision": "NO TRADE", "reason": "No bars"}
    row = features.iloc[-1]
    clock = str(row.get("clock", ""))
    if clock < "09:45" or clock >= "15:55":
        return {"decision": "NO TRADE", "reason": "Outside entry window"}
    needed = ["close", "vwap", "opening_range_high", "atr14", "relative_volume"]
    if any(pd.isna(row.get(k)) for k in needed):
        return {"decision": "NO TRADE", "reason": "Insufficient feature history"}
    checks = {
        "close_above_opening_range": float(row["close"]) > float(row["opening_range_high"]),
        "close_above_vwap": float(row["close"]) > float(row["vwap"]),
        "relative_volume_at_least_1_5": float(row["relative_volume"]) >= 1.5,
        "ema9_above_ema20": float(row["ema9"]) > float(row["ema20"]),
    }
    score = sum(checks.values()) / len(checks) * 100
    if all(checks.values()):
        return {
            "decision": "WATCH",
            "setup": "Opening-range breakout",
            "direction": "LONG",
            "score": round(score, 1),
            "close": round(float(row["close"]), 4),
            "vwap": round(float(row["vwap"]), 4),
            "opening_range_high": round(float(row["opening_range_high"]), 4),
            "atr14": round(float(row["atr14"]), 4),
            "relative_volume": round(float(row["relative_volume"]), 2),
            "reason": "All initial rule checks passed; manual review/testing only",
        }
    failed = [name for name, passed in checks.items() if not passed]
    return {"decision": "NO TRADE", "score": round(score, 1), "reason": "Failed: " + ", ".join(failed)}
