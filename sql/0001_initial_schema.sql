-- Ember, migration 0001: schemas and the transaction fact table.
-- Layers: raw (Pluggy raw payload), stg (typed, deduplicated), mart (ready for Metabase).
-- Rule: never delete raw.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS raw.pluggy_transaction (
    id bigserial PRIMARY KEY,
    item_id text NOT NULL,
    account_id text NOT NULL,
    payload jsonb NOT NULL,
    collected_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_transaction_item ON raw.pluggy_transaction (item_id);
CREATE INDEX IF NOT EXISTS idx_raw_transaction_collected ON raw.pluggy_transaction (collected_at);

CREATE TABLE IF NOT EXISTS mart.transactions (
    dedup_hash text PRIMARY KEY,
    pluggy_transaction_id text,
    date date NOT NULL,
    accrual_date date NOT NULL,
    amount numeric(14, 2) NOT NULL,
    description_raw text NOT NULL,
    description text,
    source text NOT NULL,  -- connection label, the same as in PLUGGY_ITEM_IDS (e.g. banco_a)
    movement_type text NOT NULL CHECK (movement_type IN ('account', 'credit_card')),
    account_id text NOT NULL,
    category text,
    essentiality text CHECK (essentiality IN ('committed_fixed', 'essential_variable', 'discretionary', 'gray')),
    recurring boolean,
    cancellable boolean,
    scope text,
    project text,
    installment_number integer,
    installments_total integer,
    purchase_id text,
    bill_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mart_transactions_date ON mart.transactions (date);
CREATE INDEX IF NOT EXISTS idx_mart_transactions_source ON mart.transactions (source);
CREATE INDEX IF NOT EXISTS idx_mart_transactions_essentiality ON mart.transactions (essentiality);
CREATE INDEX IF NOT EXISTS idx_mart_transactions_purchase ON mart.transactions (purchase_id);
