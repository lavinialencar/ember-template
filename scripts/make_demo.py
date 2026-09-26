#!/usr/bin/env python3
"""Builds a DEMO data/ folder, 100% made up, so you can see Ember running without a Pluggy account.

Writes, in the format Pluggy returns and the scripts expect:
  transactions.json, bills.json, accounts.json, items.json  (12 months, two banks: banco_a and banco_b)
  private_rules.json, manual_records.json                   (copied from examples/, with dates adjusted to today)
Merchants, people and documents are fictional ("Mercado Exemplo", "Padaria Modelo"); descriptions are in
Portuguese because that is what Brazilian banks send.

Usage: python3 scripts/make_demo.py [--dest FOLDER] [--force]
       python3 scripts/update.py --no-api --no-push --no-backup   (then open data/dashboard.html)
Refuses to overwrite a data/ that already has transactions.json (your real data), unless you pass --force.
"""

import argparse
import json
import os
import random
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TODAY = date.today()
OWNER_DOC = "12345678900"  # same as examples/private_rules.example.json; wrong check digit on purpose
CARDS = {"banco_a": {"closes": 3, "due": 10}, "banco_b": {"closes": 20, "due": 27}}


def add_months(d, n):
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def on_day(month, day):
    return date(month.year, month.month, min(day, 28))


class Generator:
    def __init__(self, seed=42):
        self.rnd = random.Random(seed)
        self.trans = []
        self.n = 0

    def tx(self, source, account_type, ttype, amount, d, description, category=None, hour=None, mcc=None, payer=None, receiver=None,
           installment=None, currency="BRL"):
        self.n += 1
        account = f"account-{source}-{'card' if account_type == 'CREDIT' else 'checking'}"
        when = f"{d.isoformat()}T{hour or '03:00:00'}.000Z"
        # account: outgoing is negative; card: a purchase is positive (Pluggy convention)
        sign = (-1 if ttype == "DEBIT" else 1) * (-1 if account_type == "CREDIT" else 1)
        t = {"id": f"tx-example-{self.n:06d}", "accountId": account, "date": when, "description": description, "descriptionRaw": description,
             "amount": round(sign * amount, 2), "type": ttype, "category": category, "status": "POSTED", "currencyCode": currency,
             "_source": source, "_account_name": ("Card " if account_type == "CREDIT" else "Account ") + source.replace("_", " ").title(),
             "_account_type": account_type, "paymentData": None, "creditCardMetadata": None, "merchant": None}
        if payer or receiver:
            t["paymentData"] = {k: {"name": v[0], "documentNumber": {"type": "CPF" if len(v[1]) == 11 else "CNPJ", "value": v[1]}}
                                for k, v in (("payer", payer), ("receiver", receiver)) if v}
        if account_type == "CREDIT" and ttype == "DEBIT":
            cfg = CARDS[source]
            closing = on_day(d, cfg["closes"]) if d.day < cfg["closes"] else on_day(add_months(d, 1), cfg["closes"])
            due = on_day(closing, cfg["due"])
            t["creditCardMetadata"] = {"payeeMCC": mcc, "billForecastDate": due.isoformat(), "installmentNumber": (installment or (1, 1))[0],
                                       "totalInstallments": (installment or (1, 1))[1], "_due": due.isoformat()}
        self.trans.append(t)
        return t

    def month_purchases(self, month, until):
        r = self.rnd
        shops = [  # (description, Pluggy category, MCC, times, min, max, card)
            ("MERCADO EXEMPLO", "Groceries", 5411, 7, 60, 320, "banco_a"),
            ("PADARIA MODELO", "Eating out", 5462, 8, 8, 40, "banco_a"),
            ("FARMACIA EXEMPLO", "Pharmacy", 5912, 2, 25, 120, "banco_a"),
            ("UBER *TRIP", "Taxi and ride-hailing", 4121, 6, 12, 45, "banco_a"),
            ("IFD*RESTAURANTE EXEMPLO", "Food delivery", 5812, 4, 35, 90, "banco_b"),
            ("LOJA DE ROUPAS MODELO", "Clothing", 5651, 1, 80, 260, "banco_b"),
            ("POSTO COMBUSTIVEL EXEMPLO", "Gas stations", 5541, 2, 90, 200, "banco_b"),
            ("LOJA SEM NOME 123", "Shopping", None, 2, 60, 220, "banco_b"),
            ("SERVICOS DIVERSOS XYZ", "Services", None, 1, 20, 60, "banco_a"),
        ]
        for desc, cat, mcc, times, vmin, vmax, source in shops:
            for _ in range(times):
                d = on_day(month, r.randint(1, 28))
                if d <= until:
                    self.tx(source, "CREDIT", "DEBIT", round(r.uniform(vmin, vmax), 2), d, desc, cat, f"{r.randint(8, 21):02d}:{r.randint(0, 59):02d}:00", mcc)
        for desc, cat, mcc, day, amount, source in (("STREAMING EXEMPLO", "Digital services", 4899, 12, 39.90, "banco_a"),
                                                    ("ACADEMIA EXEMPLO", "Gyms and fitness centers", 7997, 5, 119.90, "banco_b")):
            d = on_day(month, day)
            if d <= until:
                self.tx(source, "CREDIT", "DEBIT", amount, d, desc, cat, "10:00:00", mcc)
        if r.random() < 0.4 and on_day(month, 18) <= until:
            self.tx("banco_b", "CREDIT", "DEBIT", round(r.uniform(28, 60), 2), on_day(month, 18), "CINEMA MODELO", "Entertainment", "19:30:00", 7832)
        if r.random() < 0.3 and on_day(month, 8) <= until:
            self.tx("banco_a", "CREDIT", "DEBIT", round(r.uniform(90, 300), 2), on_day(month, 8), "GRAFICA MODELO", "Services", "14:10:00", 7338)


def generate(dest):
    g = Generator()
    r = g.rnd
    start = add_months(TODAY, -11)
    months = [add_months(start, i) for i in range(12)]
    company = ("Empresa Exemplo Ltda", "00000000000191")
    owner = ("Fulana Exemplo", OWNER_DOC)

    for i, month in enumerate(months):
        passed = lambda day: on_day(month, day) <= TODAY  # noqa: E731
        if passed(5):
            g.tx("banco_a", "BANK", "CREDIT", 6500.00, on_day(month, 5), "Salario EMPRESA EXEMPLO LTDA", "Salary", payer=company)
        if passed(6):
            g.tx("banco_a", "BANK", "DEBIT", 800.00, on_day(month, 6), "PIX ENVIADO Fulana Exemplo", "Same person transfer", payer=owner, receiver=owner)
            g.tx("banco_b", "BANK", "CREDIT", 800.00, on_day(month, 6), "PIX RECEBIDO Fulana Exemplo", "Same person transfer", payer=owner, receiver=owner)
        if passed(10):
            g.tx("banco_a", "BANK", "DEBIT", 2400.00, on_day(month, 10), "PIX ENVIADO IMOBILIARIA EXEMPLO", "Transfer - PIX",
                 receiver=("Imobiliaria Exemplo", "00000000000272"))
        if passed(15):
            g.tx("banco_a", "BANK", "DEBIT", round(r.uniform(170, 260), 2), on_day(month, 15), "Pagamento ENERGIA EXEMPLO SA", "Utilities")
        if passed(28):
            g.tx("banco_b", "BANK", "CREDIT", round(r.uniform(12, 20), 2), on_day(month, 28), "Rendimentos", "Proceeds interests and dividends")
        if i % 2 == 0 and passed(20):
            g.tx("banco_b", "BANK", "CREDIT", 1200.00, on_day(month, 20), "PIX RECEBIDO CLIENTE EXEMPLO", "Transfer - PIX", payer=("Cliente Exemplo", "00000000000353"))
        if i in (3, 8) and passed(12):
            g.tx("banco_a", "BANK", "CREDIT", 150.00, on_day(month, 12), "PIX RECEBIDO SEGURADORA EXEMPLO", "Transfer - PIX", payer=("Seguradora Exemplo", "00000000000434"))
        if i == 6 and passed(9):
            g.tx("banco_a", "BANK", "CREDIT", 3000.00, on_day(month, 9), "Credito consignado liberado", "Loans and financing")
        if i >= 6 and passed(11):
            g.tx("banco_a", "BANK", "DEBIT", 450.00, on_day(month, 11), "Parcela emprestimo BANCO EXEMPLO", "Loans and financing")
        if i in (7, 9) and passed(9):
            g.tx("banco_a", "BANK", "DEBIT", round(r.uniform(8, 25), 2), on_day(month, 9), "IOF", "Tax on financial operations")
        if i == 4 and passed(22):
            g.tx("banco_a", "BANK", "CREDIT", 50.00, on_day(month, 22), "PIX RECEBIDO Ciclano de Tal", "Transfer - PIX", payer=("Ciclano de Tal", "00000000001"))
        g.month_purchases(month, TODAY)

    # purchase in 6 installments: past and future installments (the future ones become future_commitment)
    purchase = on_day(add_months(TODAY, -3), 14)
    for p in range(6):
        g.tx("banco_b", "CREDIT", "DEBIT", 250.00, on_day(add_months(purchase, p), 14), f"ELETRONICOS EXEMPLO PARC {p + 1:02d}/06",
             "Electronics", "16:40:00", 5732, installment=(p + 1, 6))

    # receivable: a 300 Pix from the buyer in the last two months (matches the example manual records)
    received = []
    for n in (-2, -1):
        d = on_day(add_months(TODAY, n), 21)
        g.tx("banco_b", "BANK", "CREDIT", 300.00, d, "PIX RECEBIDO COMPRADOR EXEMPLO", "Transfer - PIX", payer=("Comprador Exemplo", "00000000002"))
        received.append(d.strftime("%d/%m"))

    # international purchase yesterday: becomes a "suspicious purchase" in the alerts
    g.tx("banco_a", "CREDIT", "DEBIT", 89.00, TODAY - timedelta(days=1), "STORE EXAMPLE LTD USA", "Online shopping", "02:14:00", 5999, currency="USD")

    # bills: group purchases by due date; only the ones already due exist in the API
    by_bill = {}
    for t in g.trans:
        m = t["creditCardMetadata"]
        if m and m["_due"] <= TODAY.isoformat():
            by_bill.setdefault((t["_source"], m["_due"]), []).append(t)
    bills = []
    for (source, due), ts in sorted(by_bill.items()):
        bid = f"bill-{source}-{due[:7]}"
        total = round(sum(abs(t["amount"]) for t in ts), 2)
        for t in ts:
            t["creditCardMetadata"]["billId"] = bid
        v = date.fromisoformat(due)
        bills.append({"id": bid, "dueDate": due + "T00:00:00.000Z", "billClosingDate": on_day(v, CARDS[source]["closes"]).isoformat() + "T00:00:00.000Z",
                      "totalAmount": total, "minimumPaymentAmount": round(total * 0.15, 2), "allowsInstallments": True,
                      "financeCharges": [], "_source": source, "_account_name": f"Card {source.replace('_', ' ').title()}"})
    # payment of each bill: the last banco_b bill is only partly paid, to demo the overdue bill alert
    last_b = max((b for b in bills if b["_source"] == "banco_b"), key=lambda b: b["dueDate"], default=None)
    for b in bills:
        v = date.fromisoformat(b["dueDate"][:10])
        paid = round(b["totalAmount"] * (0.6 if b is last_b else 1), 2)
        g.tx(b["_source"], "BANK", "DEBIT", paid, v, "Pagamento de fatura", "Credit card payment")
        g.tx(b["_source"], "CREDIT", "CREDIT", paid, v, "Pagamento recebido", "Credit card payment")
    for t in g.trans:
        if t["creditCardMetadata"]:
            t["creditCardMetadata"].pop("_due")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    accounts = []
    for source, limit in (("banco_a", 6000), ("banco_b", 3000)):
        open_amount = sum(abs(t["amount"]) for t in g.trans if t["_source"] == source and t["_account_type"] == "CREDIT" and t["type"] == "DEBIT"
                          and not t["creditCardMetadata"].get("billId"))
        name = source.replace("_", " ").title()
        accounts.append({"source": source, "id": f"account-{source}-checking", "name": f"Account {name}", "type": "BANK", "credit": None, "updated": TODAY.isoformat()})
        accounts.append({"source": source, "id": f"account-{source}-card", "name": f"Card {name}", "type": "CREDIT", "updated": TODAY.isoformat(),
                         "credit": {"creditLimit": limit, "availableCreditLimit": round(limit - open_amount, 2), "minimumPayment": None, "balanceDueDate": None}})
    items = {s: {"status": "UPDATED", "executionStatus": "SUCCESS", "lastUpdatedAt": now} for s in CARDS}

    examples = os.path.join(ROOT, "examples")
    rules = json.load(open(os.path.join(examples, "private_rules.example.json"), encoding="utf-8"))
    rec = json.load(open(os.path.join(examples, "manual_records.example.json"), encoding="utf-8"))
    rec["read_on"] = (TODAY - timedelta(days=3)).isoformat()
    rec["receivables"][0]["received"] = received

    os.makedirs(dest, exist_ok=True)
    for name, obj in (("transactions.json", g.trans), ("bills.json", bills), ("accounts.json", accounts), ("items.json", items),
                      ("private_rules.json", rules), ("manual_records.json", rec)):
        with open(os.path.join(dest, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"demo: {len(g.trans)} transactions, {len(bills)} bills, in {os.path.relpath(dest)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default=os.path.join(ROOT, "data"))
    ap.add_argument("--force", action="store_true", help="overwrites a data/ that already has transactions.json")
    a = ap.parse_args()
    if os.path.exists(os.path.join(a.dest, "transactions.json")) and not a.force:
        raise SystemExit(f"{a.dest}/transactions.json already exists (it may be your real data). Use --force to overwrite.")
    generate(a.dest)


if __name__ == "__main__":
    os.umask(0o077)
    main()
