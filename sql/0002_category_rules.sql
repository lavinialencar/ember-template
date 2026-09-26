-- Ember, migration 0002: category rules table.
-- Two sources of signal: the category Pluggy itself returns (category/categoryId,
-- which may disappear if it is a paid feature and the trial ends) and a text pattern in the
-- raw description, as a fallback that survives the trial.
-- Project rule: without confidence, it falls into 'gray'. Do not guess.
--
-- A PERSONAL rule (your name, your employer, your stores, your subscriptions, who shares the house)
-- does NOT go here: it goes in data/private_rules.json, outside git (template in examples/).
-- This table only has generic patterns, valid for anyone in Brazil.
-- The description patterns match Brazilian bank text, so they stay in Portuguese.

CREATE TABLE IF NOT EXISTS stg.category_rule (
    id bigserial PRIMARY KEY,
    description_pattern text,
    pluggy_category text,
    category text NOT NULL,
    -- null when the row is income, not an expense: essentiality does not apply to money coming in.
    essentiality text CHECK (essentiality IS NULL OR essentiality IN ('committed_fixed', 'essential_variable', 'discretionary', 'gray')),
    default_scope text,
    ignore_as_transaction boolean NOT NULL DEFAULT false,
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN stg.category_rule.ignore_as_transaction IS
    'A credit card bill payment and an internal move between your own accounts are not new spending, only reconciliation. Setting true avoids counting twice.';

COMMENT ON COLUMN stg.category_rule.description_pattern IS
    'LIKE-style pattern (% as wildcard). WARNING: Postgres LIKE is case sensitive. Whoever consumes this table matches these patterns ignoring case; if this ever becomes plain SQL, use ILIKE, never plain LIKE: "Pagamento de fatura", in lowercase, slips past a LIKE ''%PAGAMENTO%FATURA%''.';

-- Seed: only high-confidence generic patterns. Everything else falls into gray by default; it has no row here on purpose.
-- A transfer between your own accounts has NO row by name here: the strong signal is the owner's document
-- (payer and receiver with the same CPF), set in data/private_rules.json, with the name as a fallback.

INSERT INTO stg.category_rule (description_pattern, pluggy_category, category, essentiality, default_scope, ignore_as_transaction, note) VALUES
    ('%PAGAMENTO%FATURA%', 'Credit card payment', 'Credit card bill', 'gray', 'personal', true, 'Reconciliation of a bill already posted line by line, not new spending. Ignore as a double transaction.'),
    ('%Débito Automático%Fatura Cartão%', 'Credit card payment', 'Credit card bill', 'gray', 'personal', true, 'Automatic debit of the bill, same case.'),
    ('%CREDITO CONSIGNADO%', 'Loans and financing', 'Loan inflow', 'gray', 'personal', true, 'Debt money coming in, not income.'),
    ('%JUROS SALDO DEVEDOR%', 'Interests charged', 'Interest', 'committed_fixed', 'personal', false, 'The cost of being in the red.'),
    ('IOF%', 'Tax on financial operations', 'Tax on financial operations', 'committed_fixed', 'personal', false, NULL),
    ('%MERCADOLIVRE%', NULL, 'Online shopping', 'gray', NULL, false, 'Can be personal, home or work, depending on the item. Gray zone on purpose.'),
    ('%UBER%TRIP%', 'Taxi and ride-hailing', 'Transport', 'essential_variable', 'personal', false, 'Ride-hailing trip.'),
    ('%IFOOD%', 'Food delivery', 'Eating out', 'discretionary', 'personal', false, 'Delivery order.'),
    ('%IFD*%', 'Food delivery', 'Eating out', 'discretionary', 'personal', false, 'Delivery order (abbreviated description on the card).')
ON CONFLICT DO NOTHING;
