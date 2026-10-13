import os
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed

def get_recent_bars(symbol, start, end):
    """Return 5-minute bars for one symbol using the configured Alpaca feed."""
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY environment variables")
    feed_name = os.getenv("ALPACA_DATA_FEED", "iex").lower()
    feed = DataFeed.IEX if feed_name == "iex" else DataFeed.SIP
    client = StockHistoricalDataClient(key, secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame(5, TimeFrame.Unit.Minute),
        start=start,
        end=end,
        feed=feed,
        adjustment="raw",
    )
    df = client.get_stock_bars(req).df
    if df.empty:
        return df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    df = df.copy()
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df.sort_index()
