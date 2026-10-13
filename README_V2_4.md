# Moneybot V2.4: PostgreSQL execution integration (experimental)

The `PaperEngine` and Streamlit dashboard now select PostgreSQL when `DATABASE_URL` is set. SQLite remains the default when it is unset. The worker uses the same selection. Database credentials must be set privately in the hosting provider, never committed to GitHub.

## Limitations / release gates

- **Not production-ready**. PostgreSQL integration has only unit-level tests; it has not been exercised against a real Neon instance.
- PostgreSQL schema initialization and per-bar trading operations need live database integration tests, including failure injection and concurrent worker tests.
- Run only one worker instance: there is no distributed lease or row locking to prevent two workers trading the same simulated account concurrently.
- The worker may replay previously unprocessed historical bars after an outage; this must be changed before unattended paper trading.
- Simulated fills, backtesting, corporate actions, and daily loss controls require further review.
- Neon does not host the always-on worker; hosting and database persistence are separate decisions.
- No broker order submission is implemented.

## Configuration

`DATABASE_URL`: Neon PostgreSQL URL, set in a private hosting environment variable. If absent, uses SQLite (`DB_PATH`). `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are needed only for Alpaca market data; do not put secrets in `.env.example`.

Do not start the 30-day experiment until a real database integration test and safe hosting/restart tests pass.
