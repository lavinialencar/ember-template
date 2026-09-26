# How it works

![Ember architecture](../assets/architecture.svg)

Ember is a routine that runs once a day. It downloads what's new from your banks, writes it to JSON files in `data/`, applies the rules, generates the alerts, sends the push and builds the dashboard. At the end, it makes an encrypted backup. The exact order of the steps is in [02-install.md](02-install.md#the-routine-step-by-step).

## The pieces

| Piece | What it does | Where it lives |
|---|---|---|
| Pluggy | Open Finance data aggregator, authorized under Open Finance Brasil (Brazil's open banking standard); delivers statement, accounts and bills through an API | internet |
| MeuPluggy | Pluggy's free personal connection app, where you connect your banks; your Application reads those connections | internet |
| `scripts/` | the whole routine, in Python with the standard library only | your machine |
| `data/` | all your data, in JSON, out of git | your machine |
| `data/private_rules.json` | your classification rules | your machine |
| `data/manual_records.json` | what the API doesn't bring: debts, points, receivables, card details | your machine |
| `data/dashboard.html` | the dashboard, a static file | your machine |
| ntfy | delivers the push to your phone | ntfy.sh or your own server |
| Postgres, n8n | optional, for anyone who wants SQL, Metabase or an alternative load | home server |

## Fact and dimension

The mistake that ruins most homemade finance systems is treating facts and dimensions as the same thing.

| | Fact | Dimension |
|---|---|---|
| What it is | transaction, bill | rule, category, debt, card, points, subscription |
| Comes from | Pluggy, on its own | you, by hand |
| Volume | hundreds per month | dozens in total |
| Changes | almost never once closed | rarely, but it does change |
| Lives in | `data/transactions.json`, `data/bills.json` | `data/private_rules.json`, `data/manual_records.json` |

That's why Ember never writes to your two personal files. It only reads them, validates them and stops with a clear message if something is wrong. Better to generate no dashboard than to generate a wrong one in silence.

## Why Pluggy with MeuPluggy

Individuals can't join Open Finance directly: they need an authorized institution in the middle. Pluggy is that institution. MeuPluggy is its free app where you connect your banks and choose which applications to share with.

The point that matters here is consent. Resolução Conjunta nº 1 of May 4, 2020 (the joint resolution by Banco Central, Brazil's central bank, and CMN that created Open Finance Brasil) says in art. 40, § 2, item III, that institutions' control mechanisms must ensure the other institutions involved in the sharing have no access to the credentials the customer uses to identify and authenticate. In practice: when the connection is made through Open Finance, you authorize it in your bank's app, and neither Pluggy nor Ember receives your password. You can revoke it whenever you want, in the bank's app or in MeuPluggy.

This applies to connections made through Open Finance. If a bank is connected some other way, check in MeuPluggy itself how that connection works. Official text (Portuguese): [Resolução Conjunta nº 1/2020](https://normativos.bcb.gov.br/Lists/Normativos/Attachments/51028/Res_Conj_0001_v4_P.pdf).

## Why Postgres is optional

The dashboard, the alerts and the backup only need the files in `data/`. One person generates about 500 transactions a month; 10 years of that fit easily in a JSON file.

Postgres comes in when you want something else: query with SQL, hook up Metabase, or let n8n write while another tool reads. Then a client-server database makes sense. Ember generates `data/load.sql` and the scheduler loads it on its own. See [07-home-server.md](07-home-server.md).

## The layers in Postgres

The migrations in `sql/` split three layers:

| Layer | What it stores | Rule |
|---|---|---|
| `raw` | Pluggy's raw payload, as it came | never delete |
| `stg` | typed support tables, such as `stg.category_rule` | generic patterns only, never a personal rule |
| `mart` | ready to query: `mart.flow`, `mart.bill`, `mart.card_limit` and the views `v_monthly_flow` and `v_limit_usage` | what the external dashboard and Metabase read |

The classification rules don't become a table. They stay in `scripts/classify.py` and in your JSON files, because they are logic with exceptions. Postgres stores the result: one row per classified transaction.

## No duplicates

Pluggy can change a transaction after delivering it: `PENDING` becomes `POSTED`, it gets the bill's `billId`, and sometimes its `id` changes. That's why Ember doesn't stack.

- In the daily routine, `update.py` downloads only the recent window (25 days) and the future installments, and replaces that whole window per account. Anything older than the window stays as it was.
- If the API pagination comes back cut off, the old window is kept, so nothing that didn't arrive gets deleted.
- In Postgres, `build_load_sql.py` writes `INSERT ... ON CONFLICT DO UPDATE` with the key `(id, part)`. Running it again updates, it doesn't duplicate.
- The n8n workflow uses a different key: a hash of account, date, amount, description and installment number, with an ordinal to tell apart two identical transactions on the same day.

## The cash month

A card purchase doesn't leave your pocket on the day you buy. It leaves on the bill's due date. That's why each row in `data/flow.json` has `cash_month`, the month (YYYY-MM) in which the money actually moves:

- checking account: the month of the transaction itself;
- card: the month the bill is due (`billId`);
- card with no bill yet: Pluggy's forecast plus that bank's typical offset;
- installment on a bill that hasn't opened yet: becomes `future_commitment`, outside the month's spending.

Paying the bill from the account becomes `neutral`. That way the purchase counts only once, in the bill's month, and the payment doesn't count again.

## The flow types

| `flow_type` | What it is |
|---|---|
| `expense` | money going out that you consume |
| `income` | recurring money coming in, such as salary |
| `one_off_income` | money coming in that doesn't repeat: tax refund, sale, interest income |
| `reimbursement` | money coming back for something you paid for someone else or for an insurer |
| `debt_inflow` | a loan landing in the account; it's not income |
| `neutral` | transfer between your own accounts, bill payment |
| `refund` | credit that reverses an expense |
| `future_commitment` | installment already contracted that isn't due yet |

Each `expense` also gets an essentiality: `committed_fixed`, `essential_variable`, `discretionary`, `mixed` or `gray` (no safe rule). And a scope: `personal` or `business` (a company or project paid from the personal account, kept out of personal spending).

Next: [02-install.md](02-install.md).
