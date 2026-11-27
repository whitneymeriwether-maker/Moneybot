# Moneybot V3 paper staging

The free Render service deploys from `moneybot-v3-research` using
`bash Moneybot_V3/render-build.sh` and
`python Moneybot_V3/paper_status_server.py`. Its paper database is the
isolated Neon `moneybot_v3_paper` database. Apply
`Moneybot_V3/postgres_paper_schema.sql` there before deployment.

| Environment variable | Purpose |
| --- | --- |
| `MONEYBOT_V3_DATABASE_URL` | Isolated V3 Neon connection with read and write access to the paper tables |
| `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` | Free Alpaca credentials used for IEX market data |
| `V3_PAPER_TRADING_ENABLED` | Set to `0` to display the paper ledger or `1` to accept authenticated cycle requests |
| `V3_PAPER_CYCLE_TOKEN` | Random secret shared only with the HTTPS scheduler |

Configure the scheduler to send a bodyless HTTPS `POST /api/paper-cycle`
with `Authorization: Bearer <token>` every five minutes on weekdays during
the U.S. equity session. The NYSE calendar checks daylight saving time,
holidays and early closes. The free Render web service can sleep outside
the scheduling window, so the scheduler must allow for cold starts.

The first valid observation establishes the strategy baseline and records
the opening paper balance if the cash journal is empty. The strategy buys
SPY on a 0.1% rise from the previous observation using up to 80% of available
cash, and sells the position on a 0.1% decline. Fills are modeled at the IEX
quote midpoint rounded to cents. The broker order API is unused.

Check `/version` for the deployed commit and `/readyz` for a persisted
cycle. After the scheduler reports `completed`, match its cycle key in
`/automated-paper` and confirm the same row in Neon. `/healthz` checks web
process liveness. `/status` distinguishes an enabled trigger from a
verified cycle. Set the activation flag to `0` and redeploy to pause trading.
