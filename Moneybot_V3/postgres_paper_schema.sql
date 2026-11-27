-- Isolated V3 schema. This migration only creates tables and indexes.
CREATE SCHEMA IF NOT EXISTS moneybot_v3_paper;
CREATE TABLE IF NOT EXISTS moneybot_v3_paper.cash_events (
 sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 event_id text NOT NULL UNIQUE CHECK (event_id ~ '^[A-Za-z0-9_:-]{1,128}$'),
 event_type text NOT NULL CHECK (event_type IN ('paper_deposit','paper_withdrawal')),
 amount numeric(20,2) NOT NULL CHECK (amount > 0 AND amount <> 'NaN'::numeric),
 recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);
CREATE TABLE IF NOT EXISTS moneybot_v3_paper.cycle_claims (
 cycle_key text PRIMARY KEY CHECK (cycle_key ~ '^[A-Za-z0-9_.:-]{1,100}$'),
 claimed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 state text NOT NULL CHECK (state IN ('claimed','completed','failed'))
);

CREATE TABLE IF NOT EXISTS moneybot_v3_paper.automated_cycles (
 cycle_key text PRIMARY KEY,
 completed_at timestamptz NOT NULL,
 symbol text NOT NULL CHECK (symbol = 'SPY'),
 quote_timestamp timestamptz NOT NULL UNIQUE CHECK (quote_timestamp <= completed_at),
 provider text NOT NULL CHECK (provider = 'alpaca'),
 price numeric(12,2) NOT NULL CHECK (price BETWEEN 0.01 AND 1000000),
 decision text NOT NULL CHECK (decision IN ('warmup', 'hold', 'buy', 'sell', 'insufficient_cash')),
 cash numeric(20,2) NOT NULL CHECK (cash >= 0),
 equity numeric(20,2) NOT NULL CHECK (equity >= 0),
 net_deposits numeric(20,2) NOT NULL,
 realized_pnl numeric(20,2) NOT NULL,
 unrealized_pnl numeric(20,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS automated_cycles_completed_at_idx
 ON moneybot_v3_paper.automated_cycles (completed_at DESC);
CREATE TABLE IF NOT EXISTS moneybot_v3_paper.automated_fills (
 cycle_key text PRIMARY KEY REFERENCES moneybot_v3_paper.automated_cycles(cycle_key),
 side text NOT NULL CHECK (side IN ('buy', 'sell')),
 shares integer NOT NULL CHECK (shares > 0),
 realized_pnl numeric(20,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS moneybot_v3_paper.automated_positions (
 symbol text PRIMARY KEY CHECK (symbol = 'SPY'),
 shares integer NOT NULL CHECK (shares > 0),
 cost_basis numeric(20,2) NOT NULL CHECK (cost_basis > 0)
);
