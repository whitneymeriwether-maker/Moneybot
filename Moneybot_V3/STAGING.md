# V3 isolated staging service (not automatic paper trading)

`paper_status_server.py` is a **deliberately non-trading** standard-library
HTTP status endpoint. It exists only to validate that a separate free Render
service can deploy from `moneybot-v3-research` without touching the V2 service
on `main`.

It has no broker import, order submission path, background worker, market-data
feed, or database connection. It remains **NOT ACTIVATED** regardless of
environment variables. Its homepage must never be represented as paper
trading or as evidence of strategy profitability.

## Render configuration

- Repository: `whitneymeriwether-maker/Moneybot`
- Branch: `moneybot-v3-research` (never `main`)
- Plan: `free` only; do not authorize paid upgrades
- Auto-deploy: `no` until release controls and end-to-end tests exist
- Build: `python -m compileall -q Moneybot_V3/paper_status_server.py`
- Start: `python Moneybot_V3/paper_status_server.py`
- Port: `PORT` supplied by Render (defaults to 10000 locally)
- No broker credentials or database URL are needed for this staging endpoint

## Smoke tests

1. `GET /` explicitly displays **NOT ACTIVATED**.
2. `GET /healthz` returns HTTP 200, meaning only that the web process is alive.
3. `GET /status` returns `automatic_paper_trading: false` and
   `real_money_trading: false`; data and persistence are not connected.
4. `GET /readyz` returns HTTP **503** until independently validated automatic
   paper trading exists. A live web process is not trading readiness.
5. `POST /orders` returns HTTP 405; unknown routes return HTTP 404.

`python -m pytest -q tests/test_paper_status_server.py` checks these
properties locally. The main V3 CI suite also runs these tests.

## Conditions before automatic paper-trading activation

Use a separate, durable paper-only database and an authenticated,
independently timestamped market-data source. Recheck risk limits atomically
with simulated fills, make fills idempotent, preserve complete execution and
valuation history, validate restart recovery and duplicate schedules, verify
free-tier resource limits, and complete controlled shadow trials. Never
connect live brokerage order endpoints. The free Render web tier can sleep
when idle and cannot by itself guarantee uninterrupted scheduled trading.

No activation switch is implemented in this staging service. A future
trading engine must be reviewed and tested separately before any activation.
