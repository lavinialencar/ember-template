# Manual records

Some things the API doesn't bring, or brings only halfway: debts outside the card, points, who owes you, the card's closing day, the amount of the bill that's still open. They go in `data/manual_records.json`, which you fill in by reading the apps. Ember only reads this file, it never writes to it.

Template with made-up data: [`examples/manual_records.example.json`](../examples/manual_records.example.json).

## Date format

| Field | Format |
|---|---|
| `read_on`, `last_rotation`, `tax_deadline` | `YYYY-MM-DD` |
| `next_due`, `expires`, `received` | `DD/MM` (the next time that day comes around, today or later) or `DD/MM/YYYY` |

## The fields

### `read_on`

When you last read the apps. After more than 30 days, the dashboard shows "Manual records out of date".

### `cards[]`

| Field | Required | What it is |
|---|---|---|
| `source` | yes | the same label as in `PLUGGY_ITEM_IDS` |
| `name` | yes | how the card shows up on the dashboard and in alerts |
| `limit` | no | total limit |
| `open_bill` | no | amount of the open bill, read from the app. `null` lets Ember estimate it from the purchases |
| `closes`, `due` | no | closing day and due day, from 1 to 28 |
| `last_rotation` | no | when you last changed the card number (or the virtual card) |

### `debts[]`

| Field | Required | What it is |
|---|---|---|
| `name` | yes | name of the debt |
| `type` | no | `contract` (default) or `informal` |
| `balance` | one of the two | how much is left, if you know |
| `installment` and `installments_total` | one of the two | when you don't know the balance; Ember works out what's left with `installments_paid` |
| `installments_paid` | no | default 0; can't be more than `installments_total` |
| `next_due` | no | the next installment or the agreed date |
| `note` | no | free text |

### `receivables[]`

Money someone owes you, in installments.

| Field | Required | What it is |
|---|---|---|
| `name` | yes | what it's about |
| `installment` | yes | amount of each installment |
| `installments_total` | yes | how many there are |
| `received` | no | list of `DD/MM` dates of the ones already paid; can't have more than `installments_total` |
| `note` | no | free text |

### `points[]`

| Field | What it is |
|---|---|
| `program` | name of the program (required) |
| `pts` | balance in points |
| `brl` | what it's worth in reais (BRL), by your estimate |
| `expires` | when the nearest batch expires |
| `note` | free text |

### `subscriptions[]`

| Field | Default | What it is |
|---|---|---|
| `name` | required | how it shows up on the dashboard |
| `contains` | required | snippet of the charge's description |
| `amount` | `null` | monthly amount |
| `monthly` | `true` | `false` for yearly or one-off |
| `only_amount` | `null` | only counts the charge with exactly this amount |
| `detail` | `""` | plan, note |

### `tax_receipts`

So you don't reach your IR (income tax) return without the receipt for a deductible expense.

| Field | What it is |
|---|---|
| `tax_deadline` | last day to file the return, `YYYY-MM-DD` |
| `items[]` | each expense, with `description`, `has_receipt` (`true` or `false`) and `auto_uploaded` (`true` when the receipt already reaches Receita Federal, Brazil's federal tax agency, without you doing anything) |

## Example

```json
{
  "read_on": "2026-01-01",
  "cards": [
    {"source": "banco_a", "name": "Banco A", "limit": 6000, "open_bill": null, "closes": 3, "due": 10, "last_rotation": null},
    {"source": "banco_b", "name": "Banco B", "limit": 3000, "open_bill": 850.0, "closes": 20, "due": 27, "last_rotation": "2026-01-15"}
  ],
  "debts": [
    {"name": "Personal loan Banco Exemplo", "type": "contract", "installment": 450.0, "installments_total": 12, "installments_paid": 4, "next_due": "10/10", "note": "automatic debit"},
    {"name": "Financiamento Exemplo", "type": "contract", "balance": 8200.0}
  ],
  "receivables": [
    {"name": "Used equipment sale", "installment": 300.0, "installments_total": 5, "received": ["21/06", "22/07"]}
  ],
  "points": [
    {"program": "Programa de pontos Exemplo", "pts": 12000, "brl": 180.0, "expires": "15/12"}
  ],
  "subscriptions": [
    {"name": "Streaming Exemplo", "contains": "streaming exemplo", "amount": 39.9, "monthly": true, "detail": "standard plan"}
  ],
  "tax_receipts": {
    "tax_deadline": "2027-05-29",
    "items": [
      {"description": "Consulta Clínica Exemplo", "has_receipt": false, "auto_uploaded": false}
    ]
  }
}
```

## Who uses what

| Block | Dashboard | Alert |
|---|---|---|
| `cards` | name, limit, open bill | best card to buy with today, bill closing within 7 days, rotation every 6 months |
| `debts` | how much is left to pay | installment due within 10 days |
| `receivables` | received and still to receive | installment late in the month |
| `points` | value per program | points expiring within 60 days |
| `subscriptions` | what is charging | subscription that stopped charging more than 40 days ago; a monthly charge not on the list becomes "New subscription?" |
| `tax_receipts` | | missing receipt, in the 120 days before `tax_deadline` |

## Validation

The file is validated on every run by `validate_records`, in `scripts/private_config.py`. An unknown field, a date in the wrong format, a closing day outside 1 to 28, a debt with neither balance nor installments, or more installments paid than the total stops the run with a message that points to the field:

```
data/manual_records.json is invalid at debts[1]: set balance, or installment and installments_total
```

## Suggested routine

Once a month, open the apps and update `open_bill`, the debt balances, the points and the installments received. Then change `read_on` to today's date.

Next: [05-dashboard.md](05-dashboard.md).
