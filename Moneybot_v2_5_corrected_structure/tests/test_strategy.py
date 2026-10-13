import pandas as pd
from agent.strategy import build_features, find_signal

def test_empty_features_and_signal():
    empty = pd.DataFrame()
    assert build_features(empty).empty
    assert find_signal(empty)["decision"] == "NO TRADE"

def test_feature_columns_exist():
    idx = pd.date_range("2026-08-03 09:30", periods=30, freq="5min", tz="America/New_York")
    close = [10 + i * 0.02 for i in range(30)]
    bars = pd.DataFrame({
        "open": close, "high": [x + 0.05 for x in close],
        "low": [x - 0.05 for x in close], "close": close,
        "volume": [1000 + i * 50 for i in range(30)]
    }, index=idx)
    out = build_features(bars)
    for col in ["vwap", "ema9", "ema20", "atr14", "opening_range_high", "relative_volume"]:
        assert col in out.columns
