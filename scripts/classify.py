#!/usr/bin/env python3
"""Ember's normalized flow table: flow_type and cash_month of each transaction.

Reads data/transactions.json and data/bills.json (run fetch_history.py and fetch_bills.py
first), applies the rules and writes data/flow.json. Everything in data/ stays outside git.

flow_type:  expense, income, one_off_income, reimbursement, debt_inflow, neutral,
            refund, future_commitment.
cash_month: month (YYYY-MM) in which the money really moves. Card: the bill due date
            (billId), never the purchase date. Account: the transaction date itself.

Rule order: yours (data/private_rules.json, validated by private_config.py) come before
the generic ones in this file; whatever no rule catches falls into the gray zone, for you to decide.

Keyword lists below match Brazilian bank descriptions, so they stay in Portuguese.
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import date

from private_config import load_rules, norm

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TODAY = date.today().isoformat()


def desc(t):
    return t.get("descriptionRaw") or t.get("description") or ""


def side_doc(t, side):
    return (((t.get("paymentData") or {}).get(side) or {}).get("documentNumber") or {}).get("value")


def side_name(t, side):
    return ((t.get("paymentData") or {}).get(side) or {}).get("name")


# Pluggy category -> (category, essentiality), only the reliable ones (sql/0003)
PLUGGY_MAP = {
    "Hospital clinics and labs": ("Health", "essential_variable"),
    "Clothing": ("Clothing and shoes", "discretionary"),
    "Groceries": ("Groceries", "essential_variable"),
    "Pharmacy": ("Pharmacy", "essential_variable"),
    "Healthcare": ("Health", "essential_variable"),
    "Dentist": ("Health", "essential_variable"),
    "Insurance": ("Insurance", "committed_fixed"),
    "Eating out": ("Eating out", "discretionary"),
    "Food delivery": ("Eating out, delivery", "discretionary"),
    "Interests charged": ("Interest", "committed_fixed"),
    "Late payment and overdraft costs": ("Interest and late fees", "committed_fixed"),
    "Bank fees": ("Bank fees", "committed_fixed"),
    "Tax on financial operations": ("IOF", "committed_fixed"),
}
DEBT_COST = {"Interests charged", "Late payment and overdraft costs", "Bank fees", "Tax on financial operations"}

# Card merchant category code (MCC), which comes with every card purchase. Only applies when none of your rules caught it first.
MCC_MAP = {}
for _codes, _cat, _ess in [
    ((5811, 5812, 5813, 5814, 5462), "Eating out", "discretionary"),
    ((5411, 5422, 5441, 5451, 5499), "Groceries", "essential_variable"),
    ((5912, 5122), "Pharmacy", "essential_variable"),
    ((8011, 8021, 8031, 8041, 8042, 8043, 8049, 8050, 8062, 8071, 8099), "Health", "essential_variable"),
    ((4121, 4111, 4112, 4131, 4789), "Transport", "essential_variable"),
    ((5541, 5542, 5983), "Transport, fuel", "essential_variable"),
    ((5611, 5621, 5631, 5641, 5651, 5661, 5681, 5691, 5699, 5137), "Clothing and shoes", "discretionary"),
    ((5712, 5713, 5714, 5718, 5719, 5722), "Home and moving", "essential_variable"),
    ((5200, 5211, 5231, 5251, 5261, 5072), "Housing, maintenance", "essential_variable"),
    ((7832, 7841, 7922, 7929, 7932, 7933, 7941, 7991, 7992, 7993, 7994, 7996, 7997, 7998, 7999), "Leisure", "discretionary"),
    ((7230, 7297, 7298, 5977), "Personal care", "discretionary"),
    ((5940, 5941), "Leisure", "discretionary"),
    ((5942, 5943, 5945, 5947), "Books and stationery", "discretionary"),
    ((5732, 5734, 5045, 5044, 5946), "Electronics and computers", "discretionary"),
    ((7371, 7372, 7379, 4816), "Software and digital services", "discretionary"),
    ((8211, 8220, 8241, 8244, 8249, 8299), "Education", "discretionary"),
    ((7011, 7012, 4511, 4722, 4723), "Travel", "discretionary"),
    ((4814, 4899), "Phone and internet", "essential_variable"),
    ((4900,), "Utilities", "essential_variable"),
]:
    for _c in _codes:
        MCC_MAP[_c] = (_cat, _ess)

# Generic description patterns, high confidence. Yours (stores, counterparties) go in data/private_rules.json.
PATTERNS = [
    # a marketplace mixes home, personal and work in the same purchase: it stays "mixed" on purpose
    ("mercadolivre", ("Shopping (marketplace)", "mixed")),
    ("aliexpress", ("Shopping (marketplace)", "mixed")),
    ("amazon marketplace", ("Shopping (marketplace)", "mixed")),
    ("amazonmktplc", ("Shopping (marketplace)", "mixed")),
    ("amazon br", ("Shopping (marketplace)", "mixed")),
    ("uber trip", ("Transport", "essential_variable")),
    ("ifd ", ("Eating out, delivery", "discretionary")),
    ("ifood", ("Eating out, delivery", "discretionary")),
]

# Portuguese bank wording (loan, refund, card bill payment)
LOAN_WORDS = ("credito consignado", "pix no credito", "credito em parcelas", "liberacao de dinheiro", "aprovacao do credito")
REFUND_WORDS = ("reembolso", "estorno", "devolucao", "cancelado", "transferencia enviada")
CARD_PAYMENT_WORDS = ("pagamento", "fatura", "debito compulsorio", "credito de atraso", "encerramento de divida")


def load_cnpj_rules():
    """Rules per CNPJ (CNAE looked up by scripts/enrich_cnpj.py), outside git."""
    path = os.path.join(ROOT, "data", "cnpj_rules.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def in_range(r, amount):
    return (r["amount_min"] is None or amount >= r["amount_min"]) and (r["amount_max"] is None or amount <= r["amount_max"])


def counterparty_text(t):
    return norm(desc(t)) + " | " + norm(side_name(t, "receiver" if t["type"] == "DEBIT" else "payer"))


def resolve_documents(d, rules):
    """Map document -> rule snippet (patterns), found by the name in the description or in the receiver.
    After that the rule applies by document, even if the description changes."""
    docs = {}
    for t in d:
        n = counterparty_text(t)
        for r in rules["patterns"]:
            if r["contains"] in n:
                doc = side_doc(t, "receiver") if t["type"] == "DEBIT" else side_doc(t, "payer")
                if doc:
                    docs[doc] = r["contains"]
    return docs


def is_owner(t, n, rules, side):
    """Movement between the owner's own accounts: document equal to the owner's, or one of the owner's names in the description."""
    doc = rules["owner"]["document"]
    if doc and side_doc(t, side) == doc:
        return True
    return any(name in n for name in rules["owner"]["names"])


def offset_per_bank(bills, d):
    """Months between billForecastDate and the bill due date, per bank (mode)."""
    by_id = {b["id"]: b for b in bills}
    c = defaultdict(Counter)
    for t in d:
        m = t.get("creditCardMetadata") or {}
        b = by_id.get(m.get("billId"))
        if t["type"] == "DEBIT" and b and m.get("billForecastDate"):
            a, v = m["billForecastDate"], b["dueDate"][:7]
            c[t["_source"]][(int(v[:4]) - int(a[:4])) * 12 + int(v[5:7]) - int(a[5:7])] += 1
    return {f: cnt.most_common(1)[0][0] for f, cnt in c.items()}


def add_months(ym, n):
    a, m = int(ym[:4]), int(ym[5:7])
    k = a * 12 + (m - 1) + n
    return f"{k // 12}-{k % 12 + 1:02d}"


def classify(t, ctx):
    """Returns a list of rows (one, or more if the transaction is split)."""
    rules = ctx["rules"]
    n = norm(desc(t))
    day = (t.get("date") or "")[:10]
    amount = abs(t["amount"])
    card = t["_account_type"] == "CREDIT"
    credit = t["type"] == "CREDIT"
    base = {
        "id": t["id"], "date": day, "source": t["_source"], "account": t.get("_account_name"),
        "description": desc(t)[:80], "amount": amount, "category": None, "essentiality": None,
        "scope": "personal", "reason": "", "pluggy_category": t.get("category"), "card": card,
    }

    def row(ftype, cat=None, ess=None, reason="", cash_month=None, v=None, scope=None):
        r = dict(base, flow_type=ftype, category=cat, essentiality=ess, reason=reason)
        if scope:
            r["scope"] = scope
        r["cash_month"] = cash_month or (ctx["cash"](t) if card else day[:7])
        if v is not None:
            r["amount"] = v
        return [r]

    for tx in rules["neutral"]:
        if tx in n:
            return row("neutral", reason="your neutral rule (private_rules.neutral)")

    if card and not credit and "saldo em atraso" in n:
        return row("neutral", reason="overdue balance rolled over, cancelled by the overdue credit")

    # 1. card ----------------------------------------------------------------
    if card and not credit and ctx["cash"](t) > ctx["open"].get(t["_source"], "9999-99"):
        return row("future_commitment", reason="installment on a bill that has not opened yet")
    if card and credit:
        if any(k in n for k in CARD_PAYMENT_WORDS):
            return row("neutral", reason="bill payment or overdue balance settlement")
        return row("refund", reason="credit on the card")

    # 2. money coming into the account ---------------------------------------
    if credit:
        cp = counterparty_text(t)
        for r in rules["income"]:
            if r["contains"] in cp and in_range(r, amount):
                return row(r["type"], r["category"], reason="your income rule", scope=r["scope"])
        if t.get("category") == "Salary" or "salario" in n:
            return row("income", "Salary", reason="salary (Pluggy category or description)")
        if "receita federal" in n:
            return row("one_off_income", "Income tax refund", reason="Receita Federal refund batch")
        if t.get("category") == "Loans and financing" or any(k in n for k in LOAN_WORDS):
            return row("debt_inflow", "Loan", reason="debt coming in, not income")
        if is_owner(t, n, rules, "payer") or "cofrinho" in n:
            return row("neutral", reason="movement between the owner's accounts")
        if any(k in n for k in REFUND_WORDS):
            return row("refund", reason="reimbursement or refund of a payment")
        if n.startswith("rendimento") or t.get("category") == "Proceeds interests and dividends":
            return row("one_off_income", "Interest income", reason="account yield")
        if "cashback" in n:
            return row("one_off_income", "Cashback")
        return row("income", "Income to classify", "gray", reason="income with no rule")

    # 3. money leaving the account and card purchases -----------------------
    if day > TODAY:
        return row("future_commitment", reason="future installment")
    if not card:
        if "fatura" in n or n.startswith("pagamento cartao de credito") or "pagamento com saldo" in n:
            return row("neutral", reason="bill payment")
        if "quitacao antecipada" in n:
            return row("neutral", reason="early debt payoff, principal and not spending")
        doc = rules["owner"]["document"]
        if doc and side_doc(t, "receiver") == doc and side_doc(t, "payer") in (doc, None):
            return row("neutral", reason="self transfer")
        if is_owner(t, n, rules, "receiver") or "cofrinho" in n:
            return row("neutral", reason="movement between the owner's accounts")

    cp = counterparty_text(t)
    for sp in rules["splits"]:
        if sp["contains"] in cp and in_range(sp, amount):
            out = []
            for p in sp["parts"]:
                out += row(p["type"], p["category"], p["essentiality"], reason="your split", v=round(amount * p["share"], 2), scope=p["scope"])
            return out

    by_doc = ctx["docs"].get(side_doc(t, "receiver"))
    for r in rules["patterns"]:
        if (r["contains"] == by_doc or r["contains"] in cp) and in_range(r, amount):
            return row(r["type"], r["category"], r["essentiality"], reason="your rule (private_rules.patterns)", scope=r["scope"])

    for snippet, (cat, ess) in PATTERNS:
        if snippet in n:
            return row("expense", cat, ess, reason="description pattern")

    rec = re.sub(r"\D", "", side_doc(t, "receiver") or "")
    cn = re.sub(r"\D", "", (t.get("merchant") or {}).get("cnpj") or "") or (rec if len(rec) == 14 else "")
    if cn in ctx["cnpj_rules"]:
        rc = ctx["cnpj_rules"][cn]
        return row("expense", rc["category"], rc["essentiality"], reason="CNAE " + str(rc["cnae"]) + ", " + str(rc["desc"]))
    mcc = (t.get("creditCardMetadata") or {}).get("payeeMCC")
    if mcc in MCC_MAP:
        cat, ess = MCC_MAP[mcc]
        return row("expense", cat, ess, reason="MCC " + str(mcc))

    pc = t.get("category")
    if pc in PLUGGY_MAP:
        cat, ess = PLUGGY_MAP[pc]
        return row("expense", cat, ess, reason="Pluggy category" + (", cost of debt" if pc in DEBT_COST else ""))
    return row("expense", "To classify", "gray", reason="no safe rule, gray zone")


def main():
    rules = load_rules()
    d = json.load(open(os.path.join(ROOT, "data", "transactions.json"), encoding="utf-8"))
    bills = json.load(open(os.path.join(ROOT, "data", "bills.json"), encoding="utf-8"))
    by_id = {b["id"]: b for b in bills}
    offset = offset_per_bank(bills, d)
    docs = resolve_documents(d, rules)

    with open(os.path.join(ROOT, "data", "counterparty_rules.json"), "w", encoding="utf-8") as f:
        json.dump({"document_to_rule": docs}, f, ensure_ascii=False, indent=1)

    def cash(t):
        m = t.get("creditCardMetadata") or {}
        b = by_id.get(m.get("billId"))
        if b:
            return b["dueDate"][:7]
        if m.get("billForecastDate"):
            return add_months(m["billForecastDate"], offset.get(t["_source"], 0))
        return (t.get("date") or "")[:7]

    # the API does not return the open bill: the open one is the month after each bank's last due date.
    # A cash month after the open bill is a future commitment (an installment that has not opened yet), not realized spending.
    last = {}
    for b in bills:
        last[b["_source"]] = max(last.get(b["_source"], ""), b["dueDate"][:7])
    open_bill = {source: add_months(m, 1) for source, m in last.items()}
    ctx = {"docs": docs, "cash": cash, "open": open_bill, "rules": rules, "cnpj_rules": load_cnpj_rules()}
    flow = []
    for t in d:
        flow.extend(classify(t, ctx))

    # long tail: a gray counterparty under R$ 300 over the 12 months becomes "Miscellaneous (small)", mixed.
    # Only what weighs (R$ 300 or more) stays in the gray zone for you to decide.
    by_id = {x["id"]: x for x in d}

    def cp_key(r):
        x = by_id[r["id"]]
        doc = side_doc(x, "receiver") if x["type"] == "DEBIT" else side_doc(x, "payer")
        if doc and x["_account_type"] == "BANK":
            return doc
        n = re.sub(r"[0-9*/]+", " ", norm(desc(x)))
        return re.sub(r"\s+", " ", n).strip()[:24]

    total = defaultdict(float)
    for r in flow:
        if r["flow_type"] == "expense" and r["essentiality"] == "gray" and r["scope"] == "personal":
            total[cp_key(r)] += r["amount"]
    for r in flow:
        if r["flow_type"] == "expense" and r["essentiality"] == "gray" and r["scope"] == "personal" and total[cp_key(r)] < 300:
            r["category"], r["essentiality"], r["reason"] = "Miscellaneous (small)", "mixed", "small counterparty with no rule, under R$ 300"
    with open(os.path.join(ROOT, "data", "flow.json"), "w", encoding="utf-8") as f:
        json.dump(flow, f, ensure_ascii=False)

    print(f"{len(flow)} flow rows from {len(d)} transactions. Bill offset per bank: {offset}")
    print("By flow_type:", dict(Counter(r["flow_type"] for r in flow)))

    month = defaultdict(Counter)
    for r in flow:
        m = r["cash_month"]
        if r["flow_type"] in ("income", "one_off_income", "reimbursement", "debt_inflow"):
            month[m][r["flow_type"]] += r["amount"]
        elif r["flow_type"] == "expense":
            month[m]["expense"] += r["amount"]
            month[m]["gray"] += r["amount"] if r["essentiality"] == "gray" else 0
            month[m]["n_gray"] += 1 if r["essentiality"] == "gray" else 0
        elif r["flow_type"] == "refund":
            month[m]["expense"] -= r["amount"]
        elif r["flow_type"] == "future_commitment":
            month[m]["future"] += r["amount"]

    limit = max(open_bill.values(), default=TODAY[:7])
    print("\nCASH MONTH   income  one-off  reimb.  debt_inflow  expense  (gray R$, n)   future")
    for m in [k for k in sorted(month) if k <= limit][-13:]:
        c = month[m]
        print(
            f"{m}     {c['income']:>7,.0f} {c['one_off_income']:>8,.0f} {c['reimbursement']:>7,.0f} {c['debt_inflow']:>12,.0f}"
            f" {c['expense']:>8,.0f}   ({c['gray']:>6,.0f}, {c['n_gray']:>3})  {c['future']:>7,.0f}"
        )


if __name__ == "__main__":
    os.umask(0o077)
    main()
