# Dashboard

The dashboard is a single file, `data/dashboard.html`, that opens directly in your browser. It has no server, no login and no database. It follows the system's light or dark theme.

![Demo dashboard](../assets/dashboard-demo.png)

## What each section shows

| Section | What it shows |
|---|---|
| Needs attention today | the first 5 alerts, from overdue to informational, and the total of debts under contract |
| This month | income, spending, net, cost of living, new debt and debt cost so far, compared with the previous month |
| Last month | the same numbers for the last closed month, with the average of the closed months and a trend line |
| Month by month | what came in and what went out each month, with spending split by essentiality; new debt shows up separately, because it isn't income |
| Where the money goes | spending by essentiality and the 10 largest categories, as an average per closed month; rent and electricity in a typical month |
| Cards | each card's latest bills, the open bill (from the app or estimated) and the installments already contracted for the coming months |
| Subscriptions | cost per month, by `subscription_groups` group, and the list of what is charging, from the manual records |
| Debts | how much has been paid and how much is left on each debt, plus new debt and debt cost per month |
| Income still to come | receivables and account interest income |
| Points, miles and bonuses | estimated value per program and what expires first |
| Rules, where things stand | how much of the amount and of the rows is still in the gray zone, and how much is already handled by rules |

How to read the numbers:

- "Income" is salary only. 13th salary (a mandatory yearly bonus in Brazil), tax refund, reimbursement and one-off income are left out, so the average doesn't inflate.
- "Spending" is personal. What your rules mark with scope `business` shows up in a separate note.
- "Cost of living" is a floor: fixed and essential spending already classified, without debt cost.
- The first 3 months of history count as incomplete (cards take a while to show up). The current month is partial. Averages use only closed months.
- Estimated values (open bill, overdue bill still unpaid) say they are estimates. Confirm in the app.

## How it's generated

1. `scripts/dashboard_data.py` reads `flow.json`, `bills.json`, `transactions.json`, `alerts.json` and your two personal JSON files, and writes `data/dashboard.json` with the numbers already aggregated.
2. `scripts/dashboard_build.py` injects that JSON into `scripts/dashboard_template.html` and writes `data/dashboard.html`.

When it's built:

- The JSON goes inside the page's only inline script, with `</` escaped so it doesn't close the tag too early.
- Ember computes the SHA-256 of that script and puts the hash in the page's Content Security Policy. The CSP allows only that script and Chart.js from cdnjs. There is no `'unsafe-inline'` for scripts.
- Chart.js comes with Subresource Integrity (`integrity="sha384-..."`): if the file on cdnjs changes, the browser refuses it.
- The CSP also blocks any network connection from the page (`connect-src 'none'`), forms and `<base>`.
- Every piece of text that comes from outside (alert description, name in the records, rule) goes through an escape function before it enters the HTML.

To change the look, edit `scripts/dashboard_template.html` and run again:

```sh
python3 scripts/update.py --no-api --no-push --no-backup
```

If you change the Chart.js version, also change the URL in the CSP and the `integrity`.

## Never publish the dashboard

`data/dashboard.html` has your entire financial data inside it. It lives in `data/`, which `.gitignore` already ignores.

- Don't commit it, not even with `git add -f`.
- Don't upload it to GitHub Pages, Netlify, a public Drive, a pastebin or a chat.
- Don't serve it from an HTTP server open on the network. Open it as a file.
- To show the dashboard to someone, generate the demo (`make_demo.py`) in a separate copy of the repository.

Next: [06-alerts.md](06-alerts.md).
