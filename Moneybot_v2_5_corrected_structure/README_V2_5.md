# Moneybot V2.5 — Local concurrency hardening

Moneybot is strictly a **simulated, broker-disconnected** trading experiment. It does not submit orders.

## Changes
- Serialize PostgreSQL account mutations with a `FOR UPDATE` lock on the cash metadata row. All workers using the same database must use this engine for the lock to protect them.
- Use SQLite `BEGIN IMMEDIATE` for comparable local writer serialization.
- Reject out-of-order timestamps and skip empty data fetches.
- Add local concurrency and replay regression tests.

## Status / limitations
- Local tests pass; **no live Neon database integration test has been run**.
- Transaction costs, slippage, data-feed coverage, market holidays, stale-bar handling after downtime, and a full 30-day unattended test remain outstanding.
- A free Render web service that sleeps is not an always-on worker. Do not start the trial on such a service.
- No credentials are included. Never commit `.env` or `DATABASE_URL`.
- Do not treat backtest results as a prediction of future returns.

## Testing
`python -m pytest -q`

## Before deployment
Confirm PostgreSQL schema, concurrent workers, restart recovery, and connectivity using your own private Neon `DATABASE_URL`. Then validate scheduling/hosting costs and run a monitored paper-only trial.
