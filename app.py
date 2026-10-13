import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent.data import get_recent_bars
from agent.strategy import build_features, find_signal
from agent.paper import PaperLedger, RiskConfig

load_dotenv()
ET = ZoneInfo("America/New_York")

st.set_page_config(page_title="Trading Agent V1", layout="wide")
st.title("Trading Agent V1 — Research & Paper Trading")
st.caption("Simulation only • No real brokerage orders are sent")

with st.sidebar:
    st.header("Configuration")
    watchlist_text = st.text_area(
        "Watchlist (comma-separated)",
        value="AAPL,MSFT,NVDA,AMD,PLTR,SOFI,TSLA,AMZN,META,HOOD"
    )
    symbols = [s.strip().upper() for s in watchlist_text.split(",") if s.strip()]
    equity = st.number_input("Simulated starting equity ($)", min_value=100.0, value=1000.0, step=100.0)
    risk_pct = st.number_input("Risk per trade (%)", min_value=0.1, max_value=1.0, value=0.5, step=0.1) / 100
    daily_loss_pct = st.number_input("Daily stop (%)", min_value=0.5, max_value=3.0, value=1.5, step=0.5) / 100
    exposure_pct = st.number_input("Max position exposure (%)", min_value=5.0, max_value=50.0, value=25.0, step=5.0) / 100
    run_scan = st.button("Scan watchlist", type="primary")

st.info(
    "V1 uses a simple opening-range breakout hypothesis on 5-minute bars. "
    "A scan is a snapshot; the dashboard must be running and scanned during market hours to observe signals."
)

key_ok = bool(os.getenv("APCA_API_KEY_ID") and os.getenv("APCA_API_SECRET_KEY"))
if not key_ok:
    st.warning("Add your Alpaca API key and secret as environment variables to enable market data. Do not paste keys into this page or chat.")
    st.markdown("[Create a free Alpaca paper-only account](https://app.alpaca.markets/signup)")
    st.stop()

ledger = PaperLedger()
risk = RiskConfig(risk_per_trade=risk_pct, daily_loss_limit=daily_loss_pct, max_exposure=exposure_pct)

col1, col2, col3 = st.columns(3)
col1.metric("Mode", "SIMULATION ONLY")
col2.metric("Watchlist size", len(symbols))
col3.metric("Local journal", str(ledger.path))

if run_scan:
    results = []
    now = datetime.now(ET)
    start = now - timedelta(days=2)
    with st.spinner("Fetching recent 5-minute bars and evaluating setups..."):
        for symbol in symbols:
            try:
                bars = get_recent_bars(symbol, start, now)
                if bars.empty or len(bars) < 10:
                    results.append({"symbol": symbol, "decision": "NO DATA", "reason": "Not enough recent bars"})
                    continue
                feat = build_features(bars)
                signal = find_signal(feat)
                row = {"symbol": symbol, **signal}
                results.append(row)
                if signal.get("decision") == "WATCH":
                    ledger.record_signal(symbol, signal, feat.iloc[-1].to_dict())
            except Exception as exc:
                results.append({"symbol": symbol, "decision": "ERROR", "reason": str(exc)[:180]})
    df = pd.DataFrame(results)
    st.subheader("Scan results")
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("WATCH means a setup condition was observed; it does not mean a trade was executed.")

st.subheader("Simulated ledger")
signals = ledger.read_signals()
trades = ledger.read_trades()
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Recent signals**")
    st.dataframe(signals.tail(30), use_container_width=True, hide_index=True)
with c2:
    st.markdown("**Simulated trades**")
    st.dataframe(trades.tail(30), use_container_width=True, hide_index=True)

st.subheader("Risk rules configured")
st.write({
    "risk_per_trade_pct": round(risk.risk_per_trade * 100, 2),
    "daily_loss_limit_pct": round(risk.daily_loss_limit * 100, 2),
    "max_exposure_pct": round(risk.max_exposure * 100, 2),
    "starting_equity": equity,
    "short_selling": "disabled",
    "broker_orders": "disabled",
})
st.warning("This MVP logs candidate signals but does not yet automatically simulate entries/exits. That is the next development step after API/data verification.")
