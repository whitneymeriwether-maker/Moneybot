# Trading Agent V1 — 30-Day Paper-Trading MVP

This is a beginner-friendly starter project for **simulated trading only**. It does not submit real brokerage orders. It reads Alpaca market data and simulates entries/exits locally.

## What V1 does
- Uses a small, configurable watchlist (not a whole-market scanner yet).
- Calculates an opening-range breakout signal from 5-minute bars.
- Uses a fixed stop, target, one-position limit, and daily loss stop.
- Records signals and simulated trades to CSV.
- Includes a historical backtest runner.
- Starts in **simulation-only mode**. There is no live-trading code path.

## Important limitations
- This is a research prototype, not an investment recommendation or a profitable strategy claim.
- The initial strategy is deliberately simple and will likely need revision.
- Paper results are not the same as real execution. Alpaca's free data tier generally provides IEX real-time equity data, which can differ from consolidated market data.
- Do not use live brokerage keys. The app only needs data access for this prototype.
- Intraday data and the app must be running during the market session to record the full test.
- Historical results are not proof of future performance. The backtest is a first-pass validation tool and does not yet model queue position, market impact, or realistic intrabar order sequencing.

## Setup overview
1. Create a free Alpaca paper-only account: https://app.alpaca.markets/signup
2. In the dashboard, generate **paper account API keys**. Never paste keys into chat or commit them to GitHub.
3. Copy `.env.example` to `.env` and fill in the paper account key/secret.
4. Deploy this project to a cloud service that supports a persistent Python process, or run locally for initial smoke testing.
5. Install requirements and start the app.

### Local smoke test (recommended before cloud)
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Cloud deployment
For a beginner, use a private GitHub repository and a cloud Python app service. Add `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` as **secret environment variables** in the host dashboard; do not upload `.env`. Set the start command to:
```bash
streamlit run app.py --server.address 0.0.0.0 --server.port $PORT
```
Choose a host that keeps the service awake during U.S. market hours. A sleeping/free instance can miss trades and invalidate the experiment. The app is an interactive dashboard, so it is not yet a fully unattended always-on worker.

## Initial strategy (V1)
- Timeframe: 5-minute bars
- Regular session: 9:30 a.m.–4:00 p.m. US Eastern
- Opening range: first 15 minutes (9:30–9:45)
- Entry: after 9:45, bar closes above the opening-range high and above VWAP
- Exit: stop or target based on ATR-derived risk, or flatten at end of day
- One simulated position at a time
- Default max planned risk per trade: 0.5% of simulated equity
- Default daily loss stop: 1.5% of starting-of-day simulated equity
- Default maximum exposure: 25% of equity per position
- Long-only; no leverage; no shorts

These are initial research parameters, not optimized values. Position sizes are rounded down to whole shares. The system must refuse a trade if the stop distance is invalid or share quantity is zero.

## Files
- `app.py`: dashboard, live-data signal scan, and internal paper-trading simulation
- `agent/strategy.py`: feature and signal calculations
- `agent/backtest.py`: first-pass historical backtest
- `agent/paper.py`: local simulated trade ledger and risk controls
- `agent/data.py`: Alpaca data access
- `tests/test_strategy.py`: basic unit tests

## Before starting the 30-day clock
1. Confirm the data key works.
2. Confirm Eastern time and market-session handling.
3. Run backtest on multiple periods.
4. Run at least 3–5 market sessions in observation mode.
5. Start the 30-day measurement window only after the logger has been verified.

## Troubleshooting
- `401/403`: check API keys and data entitlement.
- No bars: market may be closed, symbol may be invalid, or the data feed may not contain the requested bars.
- Streamlit sleeps: use a non-sleeping host or run the market-session worker on a persistent service.
