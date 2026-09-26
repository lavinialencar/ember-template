-- Ember, migration 0003: map from Pluggy category to essentiality.
-- Pluggy returns `category` on almost every transaction. Use it as a second
-- rule level (after the description pattern of migration 0002), only for the
-- categories where the essentiality is reliable without extra context.
--
-- Do NOT add a row for an ambiguous category. `Taxi and ride-hailing`,
-- `Shopping`, `Services`, generic `Transfers` are left out on purpose:
-- transport is the canonical gray zone example ("a ride can be groceries
-- or leisure, the category does not say which").
-- No row here = it falls into gray, which is the correct behavior.
--
-- At first the gray zone is large (hundreds of rows a month, depending
-- on volume). The way forward is to review by hand: each review becomes a new rule
-- (here, or in data/private_rules.json when the rule is personal),
-- shrinking the gray zone month by month. It is not a design flaw, it is the design
-- working: the rules learn from whoever reviews.

INSERT INTO stg.category_rule (pluggy_category, category, essentiality, default_scope, ignore_as_transaction, note) VALUES
    ('Groceries', 'Groceries', 'essential_variable', 'personal', false, NULL),
    ('Pharmacy', 'Pharmacy', 'essential_variable', 'personal', false, NULL),
    ('Healthcare', 'Health', 'essential_variable', 'personal', false, NULL),
    ('Dentist', 'Health', 'essential_variable', 'personal', false, NULL),
    ('Insurance', 'Insurance', 'committed_fixed', 'personal', false, NULL),
    ('Interests charged', 'Interest', 'committed_fixed', 'personal', false, 'The cost of being in the red, redundant with the description rule of migration 0002, kept as a safety net.'),
    ('Late payment and overdraft costs', 'Interest and late fees', 'committed_fixed', 'personal', false, NULL),
    ('Bank fees', 'Bank fees', 'committed_fixed', 'personal', false, NULL),
    ('Tax on financial operations', 'IOF', 'committed_fixed', 'personal', false, 'Redundant with the description rule of migration 0002, kept as a safety net.'),
    ('Credit card payment', 'Credit card bill', 'gray', 'personal', true, 'Redundant with the description rule of migration 0002, kept as a safety net.'),
    ('Same person transfer', 'Transfer between own accounts', 'gray', 'personal', true, 'Redundant with the detection by the owner''s document and name (data/private_rules.json), kept as a safety net through the Pluggy category.'),
    ('Proceeds interests and dividends', 'Interest income', NULL, 'personal', false, 'It is income, not an expense. Essentiality does not apply.'),
    ('Income', 'Income', NULL, 'personal', false, 'It is income, not an expense. Essentiality does not apply.')
ON CONFLICT DO NOTHING;
