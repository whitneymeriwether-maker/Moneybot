# Moneybot V2.2 — paper-only development build

This project is experimental software, not investment advice or a validated strategy.

## Changes in V2.2
- Live worker bootstraps each symbol to the most recent fully completed bar on first launch, preventing fabricated historical fills on startup.
- Replayed market data after a restart does not duplicate journal activity.
- Duplicate bar timestamps and timezone-naive timestamps are rejected by the engine.
- Added safety regression tests.

## Important remaining limitations
- No live brokerage orders are implemented.
- Paper fills use OHLC bar approximations, not actual exchange fills, spreads, or slippage.
- SQLite on Render ephemeral storage will be lost on restarts/deploys. Do not deploy unattended until persistent storage is configured and verified.
- Worker and dashboard must share the same persistent database; separate Render instances do not automatically share local files.
- End-of-day exits and data gaps require additional validation; market holidays, stale data, fees, partial fills, and portfolio-wide risk behavior require tests.
- A successful test suite does not validate returns, risk, or readiness for real money.

Run tests: `python -m pytest -q`
