-- Ember, migration 0004: the result of the rules (flow), the bills and the card limits.
-- The load builder (scripts/build_load_sql.py) writes INSERT ... ON CONFLICT for these tables.
--
-- Design decision: the classification rules stay in scripts/classify.py (about 150 lines of logic
-- with exceptions, not a table). Postgres keeps the RESULT, one row per classified transaction, plus
-- the bills and the limits. Metabase reads from here. Secrets never go here: document, counterparty name and
-- private rule values stay in data/private_rules.json (outside git). This migration only creates the tables.

CREATE TABLE IF NOT EXISTS mart.flow (
    id text NOT NULL,                          -- transaction id at Pluggy
    part integer NOT NULL DEFAULT 0,           -- one transaction can become 2+ rows (split rule: a Pix half neutral, half expense)
    date date NOT NULL,
    cash_month char(7) NOT NULL,               -- YYYY-MM in which the money moves (card = bill due date)
    source text NOT NULL,                      -- connection label, the same as in PLUGGY_ITEM_IDS
    account text,
    description text,
    amount numeric(14, 2) NOT NULL,
    category text,
    essentiality text CHECK (essentiality IS NULL OR essentiality IN ('committed_fixed', 'essential_variable', 'discretionary', 'gray', 'mixed')),
    scope text,
    reason text,                               -- why the rule decided this way; it is what you review in the gray zone
    pluggy_category text,
    card boolean NOT NULL DEFAULT false,
    flow_type text NOT NULL CHECK (flow_type IN ('expense', 'income', 'one_off_income', 'reimbursement', 'debt_inflow',
                                                 'neutral', 'refund', 'future_commitment')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, part)
);

CREATE INDEX IF NOT EXISTS idx_mart_flow_cash ON mart.flow (cash_month, flow_type);
CREATE INDEX IF NOT EXISTS idx_mart_flow_source ON mart.flow (source, date);
CREATE INDEX IF NOT EXISTS idx_mart_flow_gray ON mart.flow (essentiality) WHERE essentiality = 'gray';

CREATE TABLE IF NOT EXISTS mart.bill (
    id text PRIMARY KEY,                       -- Pluggy bill id
    source text NOT NULL,
    due_date date NOT NULL,
    closing_date date,
    total numeric(14, 2) NOT NULL,
    minimum_payment numeric(14, 2),
    allows_installments boolean,
    finance_charges numeric(14, 2) NOT NULL DEFAULT 0, -- sum of financeCharges: interest, fine and IOF of the revolving balance
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mart_bill_due ON mart.bill (source, due_date);

CREATE TABLE IF NOT EXISTS mart.card_limit (
    account_id text PRIMARY KEY,
    source text NOT NULL,
    name text,
    credit_limit numeric(14, 2),
    available numeric(14, 2),                  -- can be negative: card over the limit
    minimum_payment numeric(14, 2),
    due_date date,
    read_on date NOT NULL
);

-- What a full-screen dashboard asks for most: cash month by type, without neutral (transfers between your own accounts).
CREATE OR REPLACE VIEW mart.v_monthly_flow AS
SELECT cash_month, flow_type, scope, category, essentiality,
       sum(amount) AS total, count(*) AS row_count
FROM mart.flow
WHERE flow_type <> 'neutral'
GROUP BY cash_month, flow_type, scope, category, essentiality;

-- Limit usage in %, straight from Pluggy, no estimate.
CREATE OR REPLACE VIEW mart.v_limit_usage AS
SELECT source, name, credit_limit, available,
       round(100 * (1 - available / nullif(credit_limit, 0)), 1) AS usage_pct,
       read_on
FROM mart.card_limit;
