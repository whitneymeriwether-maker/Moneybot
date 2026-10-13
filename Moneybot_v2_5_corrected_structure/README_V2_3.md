# Moneybot V2.3 — Neon integration groundwork

This release adds a Neon/PostgreSQL connection helper and schema initializer, plus tests that verify missing/invalid connection configuration is rejected. The existing trading engine **still uses SQLite**; do not deploy it as a Neon-backed worker yet. No live orders are supported.

Next engineering tasks: port the paper engine's transactions and idempotency logic to PostgreSQL; test against a disposable Neon database; add migration/rollback, shared dashboard access, and operational monitoring. Never commit DATABASE_URL or expose credentials in logs. Configure DATABASE_URL privately in Render once the PostgreSQL engine is ready.
