-- Isolated V3 only. Schema bootstrap; no initial balance, fills or trading activation.
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
