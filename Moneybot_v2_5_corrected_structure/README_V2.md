# Moneybot V2 — simulated execution prototype

No Alpaca trading client is used. `worker.py` only reads market data and records simulated fills. No real or Alpaca paper broker orders are submitted.

## Run locally

`pip install -r requirements.txt`

Set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` as private environment variables. Optionally set `ALPACA_DATA_FEED=iex`, `WATCHLIST=...`, `DB_PATH=data/moneybot.sqlite3`.

`python -m pytest -q`

`python worker.py` (continuous polling, only during regular market hours).

`streamlit run app.py` (existing research dashboard; the dashboard's old CSV journal is separate from the worker's SQLite ledger).

## Hosting warning

Render free web services sleep and their filesystem is ephemeral. **Do not deploy this worker to a free web service.** For an unattended experiment, use an always-on background worker plus a persistent disk or managed database. Verify your hosting plan's disk support and pricing before starting paid services. SQLite requires persistent storage and a single worker instance. Set `DB_PATH` to a mounted persistent location. The dashboard is not yet wired to the SQLite journal.

## Simulation limitations

- 5-minute OHLCV bars, no slippage, fees, spreads, partial fills, or halts; fills and performance are optimistic.
- Entry uses next bar open after a signal. Intrabar stop-vs-target collision assumes stop first. Gap exits use opening price.
- Only completed bars are processed. Worker polls every five minutes and may miss fills when delayed; timestamped historical replay after an outage is not equivalent to live observation.
- IEX feed is not full consolidated-market data; may materially affect signals.
- Per-symbol processing is sequential; portfolio exposure and cash depend on symbol order.
- Overnight data gaps use last available close as approximate exit; not a real fill.
- The daily realized loss stop is based on starting capital, not mark-to-market unrealized losses. No global kill switch for data outages yet.
- Existing backtest is preliminary and not a validated estimate of future performance.

**Status:** development prototype, not yet approved for a 30-day unattended trial. Test data and hosting persistence first.
