#!/usr/bin/env python3
"""Ember's alert engine: the rules live here, apart from whatever runs them.

Reads data/ (bills, manual records, connection status, transactions) and writes data/alerts.json.
Runs inside update.py (on your computer or in the server container, through scheduler.py).
Each alert has a stable key (so it does not duplicate a TickTick task), a level
(overdue, warning, info) and whether it needs action from you (action=True becomes a push and a task; the rest stays on the dashboard).

Alerts: overdue bill, minimum payment due, card limit maxed out, subscription missing or new, best card,
late receivable, missing tax receipt, card rotation, suspicious purchase, bill closing,
debt due, points expiring, stalled connection, stale manual records.
The manual data (debts, receivables, points, cards, subscriptions) comes from data/manual_records.json.
"""

import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from private_config import load_records

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TODAY = date.today()


def read(name, default):
    path = os.path.join(ROOT, "data", name)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def dmy(txt):
    """'30/09' or '02/11/2026' -> the next date with that day, today or in the future."""
    p = txt.split("/")
    d, m = int(p[0]), int(p[1])
    year = int(p[2]) if len(p) > 2 else TODAY.year
    target = date(year, m, d)
    if len(p) <= 2 and target < TODAY:
        target = date(year + 1, m, d)
    return target


def slug(txt):
    return re.sub(r"[^a-z0-9]+", "_", norm(txt)).strip("_")[:40] or "item"


def brl(v):
    return f"R$ {v:,.2f}"


def dm(d):
    return d.strftime("%b %d")


def full(d):
    return d.strftime("%b %d, %Y")


def main():
    rec = load_records()
    names = {c["source"]: c["name"] for c in rec["cards"]}
    bills = read("bills.json", [])
    items = read("items.json", {})
    out = []

    def add(key, level, title, detail, due=None, action=True, short=None):
        out.append({"key": key, "level": level, "title": title, "detail": detail, "short": short or detail, "due": due, "action": action})

    # 1. overdue bill. The bill API does NOT say what was paid (payments comes back empty), so the payment
    # is inferred from the "bill payment" credits on the card itself, assigned to the bill with the
    # closest due date. It is an estimate: confirm in the bank app.
    flow = read("flow.json", [])
    payments = [r for r in flow if r["flow_type"] == "neutral" and r.get("card") and ("bill" in r["reason"] or "settlement" in r["reason"])]
    by_source = defaultdict(list)
    for b in bills:
        by_source[b["_source"]].append(b)
    paid = defaultdict(float)
    for r in payments:
        dp = date.fromisoformat(r["date"])
        cand = [(abs((date.fromisoformat(b["dueDate"][:10]) - dp).days), b["id"]) for b in by_source[r["source"]]]
        cand = [c for c in cand if c[0] <= 20]
        if cand:
            paid[min(cand)[1]] += r["amount"]
    # A bill with finance charges (revolving balance) already carries the unpaid balance of the previous one on the same card.
    # Without this the same balance counts twice (the next bill already adds the previous balance).
    rolled = set()
    for b in bills:
        if sum(c["amount"] for c in b.get("financeCharges") or []) > 0:
            v = date.fromisoformat(b["dueDate"][:10])
            for a in by_source[b["_source"]]:
                if 0 < (v - date.fromisoformat(a["dueDate"][:10])).days <= 45:
                    rolled.add(a["id"])
    unpaid = []
    for b in bills:
        due = date.fromisoformat(b["dueDate"][:10])
        if b["id"] in rolled or due >= TODAY or due < TODAY - timedelta(days=60) or (b.get("totalAmount") or 0) <= 20:
            continue
        balance = round(b["totalAmount"] - paid[b["id"]], 2)
        if balance > max(20, 0.05 * b["totalAmount"]):
            name = names.get(b["_source"], b["_source"])
            unpaid.append((due, name, balance, b["totalAmount"]))
    open_bills = [{"card": a[1], "due": a[0].isoformat(), "balance": a[2], "total": a[3]} for a in sorted(unpaid)]
    if unpaid:
        unpaid.sort()
        total = sum(a[2] for a in unpaid)
        parts = "; ".join(f"{a[1]} {a[0].strftime('%b %Y')}: {brl(a[2])} of {brl(a[3])}" for a in unpaid)
        add("overdue-bills", "overdue", f"Overdue bills still open, {brl(total)} (estimated)",
            f"{parts}. Estimated from the payments found in the statement, confirm in the apps. An overdue bill balance goes to revolving credit, with high interest.", unpaid[0][0].isoformat(),
            short=", ".join(sorted({a[1] for a in unpaid})) + ". Estimated from the statement, confirm in the apps.")

    # 1b. card minimum payment due within 3 days. A closed bill comes from the API (with the minimum); while the bill
    # is still open the API does not return it, so the due date is projected from the same day of month as the last bill.
    for source, bs in by_source.items():
        if not bs:  # a bank with a payment in the statement but no bill in the API
            continue
        name = names.get(source, source)
        api_due = set()
        for b in bs:
            due = date.fromisoformat(b["dueDate"][:10])
            api_due.add(due)
            days = (due - TODAY).days
            minimum = b.get("minimumPaymentAmount") or 0
            if 0 <= days <= 3 and (b.get("totalAmount") or 0) > 20 and paid[b["id"]] < minimum:
                add(f"minimum-{source}-{due.isoformat()}", "warning", f"Card {name} due in {days} day(s)",
                    f"due {dm(due)}, minimum {brl(minimum)} of {brl(b['totalAmount'])}. Paying the minimum avoids the late status and the fine.",
                    due.isoformat(), short=f"{name} due {dm(due)}.")
        last = max(date.fromisoformat(b["dueDate"][:10]) for b in bs)
        for extra_month in (0, 1):
            m = TODAY.month + extra_month
            year, m = TODAY.year + (m - 1) // 12, (m - 1) % 12 + 1
            try:
                proj = date(year, m, last.day)
            except ValueError:
                continue
            if 0 <= (proj - TODAY).days <= 3 and proj not in api_due:
                add(f"minimum-{source}-{proj.isoformat()}", "warning", f"Card {name} due in {(proj - TODAY).days} day(s)",
                    f"due {dm(proj)}; the bill has not closed in the API yet, check the amount and the minimum in the app.",
                    proj.isoformat(), short=f"{name} due {dm(proj)}.")

    # 1c. card limit maxed out. Reads the limit and the available amount that Pluggy reports (data/accounts.json,
    # written by update.py); estimates nothing. Warns once a month per card.
    for c in read("accounts.json", []):
        cd = c.get("credit") or {}
        if c.get("type") != "CREDIT" or not cd.get("creditLimit"):
            continue
        used = 1 - (cd.get("availableCreditLimit") or 0) / cd["creditLimit"]
        if used >= 0.9:
            name = names.get(c["source"], c["source"])
            add(f"limit-{c['source']}-{TODAY.strftime('%Y-%m')}", "warning", f"{name} limit maxed out",
                f"{used * 100:.0f}% of the limit in use (available {brl(cd.get('availableCreditLimit') or 0)} of {brl(cd['creditLimit'])}). No room for a new purchase, and above 100% there may be a fee.",
                short=f"{name} {used * 100:.0f}% of the limit.")

    # 1d. subscriptions. Known ones: manual_records.subscriptions (name, contains, monthly, only_amount). "Missing" = a known
    # monthly one with no charge for more than 40 days (it may have failed). "New" = a charge that repeats every month, with a
    # stable amount, that is not on the list. Installments and Pix do not count. You decide what goes on the list.
    known = [dict(a, key=a["contains"]) for a in rec["subscriptions"]]
    trans = read("transactions.json", [])
    for k in known:
        if not k.get("monthly"):
            continue
        dates = sorted(x["date"][:10] for x in trans if x["type"] == "DEBIT" and k["key"] in norm(x["description"] + " " + (x.get("descriptionRaw") or ""))
                       and (k.get("only_amount") is None or round(abs(x["amount"]), 2) == k["only_amount"]) and x["date"][:10] <= TODAY.isoformat())
        if len({d[:7] for d in dates}) >= 3 and (TODAY - date.fromisoformat(dates[-1])).days > 40:
            days = (TODAY - date.fromisoformat(dates[-1])).days
            add(f"subscription-missing-{slug(k['key'])}-{dates[-1][:7]}", "warning", f"Subscription with no charge: {k['name']}",
                f"last charge on {dm(date.fromisoformat(dates[-1]))}, {days} days ago. It may have failed or been cancelled.",
                short=f"{k['name']}, {days} days with no charge.")
    groups = defaultdict(list)
    for x in trans:
        d = x["date"][:10]
        cat = (x.get("category") or "").lower()
        if x["type"] != "DEBIT" or x.get("status") == "PENDING" or d > TODAY.isoformat() or "transfer" in cat or "pix" in cat or "loan" in cat:
            continue
        if ((x.get("creditCardMetadata") or {}).get("totalInstallments") or 1) > 1:
            continue
        # strips Portuguese filler words that banks put in descriptions
        n = re.sub(r"\b(pix|enviado|recebido|compra|debito|credito|pagamento|de|da|do|em|parc|cp)\b", " ", re.sub(r"[^a-z ]", " ", norm(x["description"])))
        key = " ".join(n.split()[:2])
        if key:
            groups[key].append((d, abs(x["amount"])))
    new = 0
    for key, v in sorted(groups.items()):
        months = defaultdict(int)
        for d, _ in v:
            months[d[:7]] += 1
        vals = sorted(a for _, a in v)
        med = vals[len(vals) // 2]
        stable = sum(1 for a in vals if abs(a - med) <= 0.15 * med) / len(vals)
        recent = (TODAY - date.fromisoformat(max(d for d, _ in v))).days <= 45
        if len(months) >= 3 and max(months.values()) <= 1 and stable >= 0.8 and recent and not any(k["key"] in key or key in k["key"] for k in known) and new < 3:
            new += 1
            add(f"subscription-new-{slug(key)}", "warning", f"New subscription? {key}",
                f"a charge of about {brl(med)} in {len(months)} months in a row that is not on the list of known subscriptions. If it is a subscription, add it to the list; if not, ignore it.",
                short="Monthly charge that is not in the records.")

    # 1e. best card to buy with today: the one that gives the most days until you pay (closing and due day come from
    # manual_records.cards). A purchase on the closing day falls on the next bill. Only counts cards with free limit.
    free = {c["source"]: (c.get("credit") or {}).get("availableCreditLimit") or 0 for c in read("accounts.json", [])}
    options = []
    for c in rec["cards"]:
        if not c["closes"] or not c["due"]:
            continue
        closes = date(TODAY.year, TODAY.month, c["closes"]) if TODAY.day < c["closes"] else date(TODAY.year + (TODAY.month // 12), TODAY.month % 12 + 1, c["closes"])
        d_year, d_month = (closes.year, closes.month) if c["due"] > closes.day else (closes.year + (closes.month // 12), closes.month % 12 + 1)
        options.append(((date(d_year, d_month, c["due"]) - TODAY).days, c["name"], free.get(c["source"], 0)))
    with_limit = [o for o in options if o[2] > 50]
    if options:
        if with_limit:
            d, n, lv = max(with_limit)
            add(f"best-card-{TODAY.isoformat()}", "info", f"Best card to buy with today: {n}", f"{n}, {d} days until you pay, with {brl(lv)} of free limit.", action=False)
        else:
            add(f"best-card-{TODAY.isoformat()}", "info", "Best card to buy with today: none", "No card in your records has free limit. New purchases only by debit or Pix.", action=False)

    # 1f. late receivable (manual_records.receivables: installment, installments_total, received "DD/MM"). Alerts from the
    # day after the latest day seen, if the current month has not been received yet.
    for rb in rec["receivables"]:
        got = [tuple(int(x) for x in r.split("/")[:2]) for r in rb["received"]]
        if got and len(got) < rb["installments_total"] and not any(m == TODAY.month for _, m in got) and TODAY.day > max(d for d, _ in got):
            add(f"receivable-{slug(rb['name'])}-{TODAY.strftime('%Y-%m')}", "warning", f"Late receivable: {rb['name']}",
                f"the {brl(rb['installment'])} installment for {TODAY.strftime('%b %Y')} has not arrived (it usually arrives by day {max(d for d, _ in got)}). {len(got)} of {rb['installments_total']} received.",
                short="Receivable installment has not arrived yet.")

    # 1g. missing tax receipt, before the income tax (IR) return (Receita Federal usually opens it in March and closes it on May 31).
    # List in manual_records.tax_receipts (tax_deadline and items).
    tr = rec["tax_receipts"] or {}
    if tr and date(TODAY.year, 1, 1) <= TODAY and date.fromisoformat(tr.get("tax_deadline", "2099-01-01")) - timedelta(days=120) <= TODAY <= date.fromisoformat(tr.get("tax_deadline", "2099-01-01")):
        missing = [i for i in tr["items"] if not i["has_receipt"] and not i["auto_uploaded"]]
        if missing:
            add(f"missing-receipts-{TODAY.strftime('%Y-%m')}", "warning", f"{len(missing)} tax receipt(s) missing for the income tax return",
                f"return deadline: {full(date.fromisoformat(tr['tax_deadline']))}. Missing: " + ", ".join(i["description"] for i in missing) + ".",
                tr["tax_deadline"], short=f"{len(missing)} deductible expenses still without a receipt.")

    # 1h. card rotation (new number or virtual card): 6 months after the last change,
    # manual_records.cards[].last_rotation. With no date, the alert stays quiet.
    for c in rec["cards"]:
        last = c.get("last_rotation")
        if not last:
            continue
        u = date.fromisoformat(last)
        m = u.month + 6
        due = date(u.year + (m - 1) // 12, (m - 1) % 12 + 1, min(u.day, 28))
        if TODAY >= due:
            add(f"rotation-{c['source']}-{last}", "warning", f"Rotate card {c['name']}",
                f"last rotation on {full(u)}, 6 months have passed (it was due {full(due)}). Replace the card and update it wherever it is saved.",
                due.isoformat(), short=f"{c['name']}, last change {u.strftime('%b %Y')}.")

    # 1i. suspicious card purchase (scripts/suspicious.py). Looks at the last 3 days; Pluggy updates once a day,
    # so the warning may arrive up to 24h after the purchase (blocking on the spot is the bank app's job). "It was me"
    # (the Ignore button) teaches: that purchase's category and merchant stop being new on the next run.
    import suspicious
    alert_state = read("alerts_state.json", {})
    known_mcc, known_merchants = set(), set()
    by_id = {x["id"]: x for x in trans}
    for k in alert_state.get("ignored", []):
        if k.startswith("suspicious-") and k[len("suspicious-"):] in by_id:
            x = by_id[k[len("suspicious-"):]]
            known_mcc.add(suspicious.mcc(x))
            known_merchants.add(suspicious.merchant(x["description"]))
    found = suspicious.analyze(trans, TODAY - timedelta(days=2), TODAY, known_mcc, known_merchants)
    for a in sorted(found, key=lambda a: a["date"], reverse=True)[:5]:
        card = names.get(a["card"], a["card"])
        when_txt = dm(datetime.fromisoformat(a["date"].replace("Z", "+00:00")))
        add(f"suspicious-{a['id']}", "overdue", f"Suspicious purchase on card {card}: {a['merchant']}",
            f"{when_txt}, {brl(a['amount'])} at {a['merchant']}. Reason: {'; '.join(a['reasons'])}. If it was not you, block the card in the app and dispute the purchase.",
            short=f"{card}, {a['merchant']} ({'; '.join(a['reasons'])}).")

    # 2. bill closing (the open bill amount only comes from the app, so it uses the manual records)
    for c in rec["cards"]:
        if not c["closes"] or c["open_bill"] is None:
            continue
        f = date(TODAY.year, TODAY.month, c["closes"])
        if f < TODAY:
            f = date(TODAY.year + TODAY.month // 12, TODAY.month % 12 + 1, c["closes"])
        if (f - TODAY).days <= 7:
            add(f"bill-closing-{c['source']}-{f.isoformat()}", "warning", f"{c['name']} bill closing",
                f"closes {dm(f)}, {brl(c['open_bill'])} as of the last app reading", f.isoformat(), action=False)

    # 3. debt due within 10 days (contract or informal, manual_records.debts[].next_due)
    for d in rec["debts"]:
        if d["next_due"]:
            target = dmy(d["next_due"])
            if (target - TODAY).days <= 10:
                amount = d["installment"] if d["installment"] is not None else d["balance"]
                title = ("Pay back: " if d["type"] == "informal" else "Installment due: ") + d["name"]
                add(f"debt-{slug(d['name'])}-{target.isoformat()}", "warning", title, f"{brl(amount)} due {dm(target)}", target.isoformat())

    # 4. points or bonus expiring within 60 days
    for p in rec["points"]:
        if not p["expires"]:
            continue
        target = dmy(p["expires"])
        days = (target - TODAY).days
        if 0 <= days <= 60:
            how_much = brl(p["brl"]) if p["brl"] else f"{p['pts']:,.0f} points"
            add(f"points-{slug(p['program'])}-{target.isoformat()}", "warning" if days <= 30 else "info", f"Points expiring: {p['program']}",
                f"{how_much} expire on {full(target)}, {days} days left", target.isoformat())

    # 6. stalled connection
    for source, st in items.items():
        last = st.get("lastUpdatedAt")
        stale = False
        if last:
            stale = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(last.replace("Z", "")[:19])).days >= 3
        if st.get("status") != "UPDATED" or st.get("executionStatus") not in ("SUCCESS", None) or stale:
            add(f"connection-{source}", "overdue", f"Connection stalled: {source}", f"status {st.get('status')}, last update {str(last)[:10]}. Without reconnecting, the statement silently stops growing.")

    # 7. stale manual records
    read_on = rec["read_on"]
    if read_on and (TODAY - date.fromisoformat(read_on)).days > 30:
        add("stale-records", "info", "Manual records out of date", f"read on {dm(date.fromisoformat(read_on))}: open bill, points, debts and receivables need a fresh reading from the apps", action=False)

    order = {"overdue": 0, "warning": 1, "info": 2}
    out.sort(key=lambda a: (order[a["level"]], a["due"] or "9999"))
    with open(os.path.join(ROOT, "data", "alerts.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": TODAY.isoformat(), "items": out, "open_bills": open_bills}, f, ensure_ascii=False, indent=1)
    print(f"alerts: {len(out)} ({sum(1 for a in out if a['action'])} need action)")
    for a in out:
        print(f"  [{a['level']}] {a['title']} | {a['detail'][:80]}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
