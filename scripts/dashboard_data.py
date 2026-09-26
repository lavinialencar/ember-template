#!/usr/bin/env python3
"""Aggregates data/flow.json and data/bills.json into data/dashboard.json, the base of Ember's dashboard.

Outside git (data/). The manual data (debts, receivables, points, cards, subscriptions) comes from
data/manual_records.json; the subscription groups for the chart come from data/private_rules.json.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import date

from private_config import load_records, load_rules, norm

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.umask(0o077)  # data/dashboard.json is owner-only
flow = json.load(open(os.path.join(ROOT, "data", "flow.json"), encoding="utf-8"))
bills = json.load(open(os.path.join(ROOT, "data", "bills.json"), encoding="utf-8"))
t = json.load(open(os.path.join(ROOT, "data", "transactions.json"), encoding="utf-8"))
REC = load_records()
RULES = load_rules()
_ALERTS = os.path.join(ROOT, "data", "alerts.json")
ALERTS = json.load(open(_ALERTS, encoding="utf-8")) if os.path.exists(_ALERTS) else {"items": [], "open_bills": []}

TODAY = date.today()
CUR = TODAY.strftime("%Y-%m")
DEBT_COST = ("Interest", "Bank fees", "IOF", "Debt cost")


def add_months(ym, n):
    k = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{k // 12}-{k % 12 + 1:02d}"


# rolling window: the 12 months up to the current one. Cards only show up well after the first month of data,
# so the first 3 months of history are "incomplete"; the current one is partial; the rest are closed.
MONTHS = [add_months(CUR, -k) for k in range(11, -1, -1)]
_FIRST = min(x["date"][:7] for x in t)
INCOMPLETE = {m for m in MONTHS if m <= add_months(_FIRST, 2)}
PARTIAL = {CUR}
CLOSED = [m for m in MONTHS if m not in INCOMPLETE and m not in PARTIAL]
NC = max(len(CLOSED), 1)


def r0(x):
    return int(round(x))


month = {m: defaultdict(float) for m in MONTHS}
for r in flow:
    m = r["cash_month"]
    if m not in month:
        continue
    v, ft = r["amount"], r["flow_type"]
    if r.get("scope", "personal") != "personal":  # business scope (company, project) paid or received on the personal side: left out, only in a note
        if ft == "expense":
            month[m]["business"] += v
        elif ft in ("income", "one_off_income"):
            month[m]["business_income"] += v
        continue
    if ft == "income":
        month[m]["bonus13" if (r["category"] or "").startswith("13th") else ("salary" if r["category"] == "Salary" else "other")] += v
    elif ft == "one_off_income":
        month[m]["one_off"] += v
    elif ft == "reimbursement":
        month[m]["reimbursement"] += v
    elif ft == "debt_inflow":
        month[m]["debt_inflow"] += v
    elif ft == "expense":
        month[m]["spend_" + (r["essentiality"] or "gray")] += v
        cat = r["category"] or ""
        if cat.startswith(DEBT_COST):
            month[m]["debt_cost"] += v
        if cat.startswith("Equipment"):
            month[m]["equipment"] += v
    elif ft == "refund":
        month[m]["refund"] += v

month_rows = []
for m in MONTHS:
    d = month[m]
    spend = d["spend_committed_fixed"] + d["spend_essential_variable"] + d["spend_discretionary"] + d["spend_mixed"] + d["spend_gray"] - d["refund"]
    month_rows.append({
        "month": m, "incomplete": m in INCOMPLETE, "partial": m in PARTIAL,
        "salary": r0(d["salary"]), "bonus13": r0(d["bonus13"]), "one_off": r0(d["one_off"]), "reimbursement": r0(d["reimbursement"]),
        "other": r0(d["other"]), "debt_inflow": r0(d["debt_inflow"]), "spend": r0(spend),
        "fixed": r0(d["spend_committed_fixed"]), "essential": r0(d["spend_essential_variable"]),
        "discretionary": r0(d["spend_discretionary"]), "mixed": r0(d["spend_mixed"]), "gray": r0(d["spend_gray"]), "refund": r0(d["refund"]),
        "debt_cost": r0(d["debt_cost"]), "equipment": r0(d["equipment"]), "business": r0(d["business"]), "business_income": r0(d["business_income"]),
    })


def average(field, months=CLOSED):
    return sum(x[field] for x in month_rows if x["month"] in months) / NC


def group(c):
    """Folds subcategories into the same family: 'Housing, electricity' and 'Housing, rent' are split out of 'Housing'."""
    g = (c or "").split(",")[0].strip()
    if g == "Housing":
        sub = (c.split(",")[1].strip().lower() if "," in c else "")
        return "Rent" if sub.startswith("rent") else "Electricity" if sub.startswith("electricity") else "Home maintenance"
    return g


# categories (closed months), only the classified ones, and gray by Pluggy type
cat = Counter()
gray_pluggy = Counter()
gray_n = Counter()
reasons = defaultdict(lambda: [0, 0.0])
for r in flow:
    if r["flow_type"] != "expense" or r["cash_month"] not in CLOSED or r.get("scope", "personal") != "personal":
        continue
    if r["essentiality"] == "gray":
        gray_pluggy[r["pluggy_category"] or "No type"] += r["amount"]
        gray_n[r["pluggy_category"] or "No type"] += 1
        k = "no safe rule"
    else:
        if not (r["category"] or "").startswith("Equipment"):
            cat[group(r["category"])] += r["amount"]
        k = "rule"
    reasons[k][0] += 1
    reasons[k][1] += r["amount"]

# bills per card: one card per source label that has bills; name and limit come from the manual records
CARD_REC = {c["source"]: c for c in REC["cards"]}
last = {}
for b in bills:
    last[b["_source"]] = max(last.get(b["_source"], ""), b["dueDate"][:7])

cards = []
future_month = defaultdict(float)
for source in sorted(last):
    cc = CARD_REC.get(source, {})
    open_m = add_months(last[source], 1)
    closed_bills = sorted([b for b in bills if b["_source"] == source], key=lambda b: b["dueDate"])[-4:]
    est = sum(r["amount"] for r in flow if r["source"] == source and r["card"] and r["flow_type"] == "expense" and r["cash_month"] == open_m)
    est -= sum(r["amount"] for r in flow if r["source"] == source and r["card"] and r["flow_type"] == "refund" and r["cash_month"] == open_m)
    from_app = cc.get("open_bill") is not None
    cards.append({
        "name": cc.get("name", source), "limit": cc.get("limit"),
        "closed": [{"due": b["dueDate"][:10], "total": r0(max(b["totalAmount"], 0))} for b in closed_bills],
        "open_month": open_m, "open_estimate": r0(cc["open_bill"] if from_app else est), "open_from_app": from_app,
    })
for r in flow:
    if r["flow_type"] == "future_commitment" and r["card"]:
        future_month[r["cash_month"]] += r["amount"]
OPEN = cards[0]["open_month"] if cards else add_months(CUR, 1)


# subscriptions: chart groups in private_rules.subscription_groups; items (what charges today) in the manual records
def rows_of(key, only_amount=None, exclude_amount=None):
    out = []
    for x in t:
        if x["type"] != "DEBIT":
            continue
        n = norm(x.get("description", "") + " " + (x.get("descriptionRaw") or ""))
        v = round(abs(x["amount"]), 2)
        if key in n and (only_amount is None or v == only_amount) and (exclude_amount is None or v != exclude_amount):
            out.append((x["date"][:10], v))
    return sorted(out)


GROUPS = list(dict.fromkeys(g["group"] for g in RULES["subscription_groups"]))
sub_month = {m: defaultdict(float) for m in MONTHS}
sporadic = defaultdict(float)
for g in RULES["subscription_groups"]:
    for d, v in rows_of(g["contains"], g["only_amount"], g["exclude_amount"]):
        if d[:7] in sub_month:
            sub_month[d[:7]][g["group"]] += v
            if g["sporadic"]:
                sporadic[g["group"]] += v
subs = {
    "groups": GROUPS,
    "months": [{"month": m, **{g: round(sub_month[m][g], 2) for g in GROUPS}} for m in MONTHS],
    "items": [{"name": a["name"], "amount": a["amount"] or 0, "detail": a["detail"]} for a in REC["subscriptions"] if a["monthly"]],
    "sporadic": [{"name": g, "total12": round(v, 2)} for g, v in sporadic.items()],
}

# Housing: the amount of a normal month (median), because the mean dilutes when a month is missing
_rent = [r for r in flow if r["flow_type"] == "expense" and (r["category"] or "") == "Housing, rent"]
_elec = [r for r in flow if r["flow_type"] == "expense" and (r["category"] or "") == "Housing, electricity"]
housing = {
    "rent": {"typical": r0(sorted(r["amount"] for r in _rent)[len(_rent) // 2]) if _rent else 0, "months": len({r["cash_month"] for r in _rent})},
    "electricity": {"avg": r0(sum(r["amount"] for r in _elec) / len(_elec)) if _elec else 0, "min": r0(min((r["amount"] for r in _elec), default=0)),
                    "max": r0(max((r["amount"] for r in _elec), default=0)), "months": len({r["cash_month"] for r in _elec})},
}


def debt(d):
    paid = round(d["installments_paid"] * d["installment"], 2) if d["installment"] is not None else None
    if d["balance"] is not None:
        to_pay = d["balance"]
    else:
        to_pay = round((d["installments_total"] - d["installments_paid"]) * d["installment"], 2)
    return {**d, "to_pay": to_pay, "paid": paid}


interest = sum(r["amount"] for r in flow if r["category"] == "Interest income" and r["cash_month"] in CLOSED)
out = {
    "open_bills": ALERTS.get("open_bills", []),
    "alerts": ALERTS.get("items", []),
    "generated": TODAY.isoformat(), "months": month_rows, "closed": CLOSED, "read_on": REC["read_on"],
    "ref": {"current": CUR, "previous": add_months(CUR, -1), "previous2": add_months(CUR, -2), "open": OPEN},
    "avg": {k: r0(average(k)) for k in ("salary", "spend", "fixed", "essential", "discretionary", "mixed", "gray", "debt_cost", "debt_inflow", "refund")},
    "categories": [{"name": k, "amount": r0(v / NC)} for k, v in cat.most_common(10)],
    "interest_income": {"total": r0(interest), "avg": r0(interest / NC)},
    "housing": housing,
    "business": {"cost": sum(x["business"] for x in month_rows if x["month"] in CLOSED), "income": sum(x["business_income"] for x in month_rows if x["month"] in CLOSED)},
    "one_offs": [{"name": "Equipment (one-off purchases)", "amount": r0(sum(r["amount"] for r in flow if r["flow_type"] == "expense" and (r["category"] or "").startswith("Equipment")))}],
    "gray_pluggy": [{"type": k, "amount": r0(v / NC), "rows": gray_n[k]} for k, v in gray_pluggy.most_common(10)],
    "coverage": {"rule_rows": reasons["rule"][0], "rule_amount": r0(reasons["rule"][1]),
                 "gray_rows": reasons["no safe rule"][0], "gray_amount": r0(reasons["no safe rule"][1])},
    "cards": cards, "card_future": [{"month": k, "amount": r0(v)} for k, v in sorted(future_month.items())],
    "subscriptions": subs,
    "points": REC["points"],
    "receivables": REC["receivables"],
    "debts": [debt(d) for d in REC["debts"]],
    "n_rules": len(RULES["patterns"]) + len(RULES["income"]) + len(RULES["splits"]),
    "debt_inflow_12m": r0(sum(x["debt_inflow"] for x in month_rows)),
    "debt_cost_12m": r0(sum(x["debt_cost"] for x in month_rows)),
    "debt_cost_open": r0(sum(r["amount"] for r in flow if r["flow_type"] == "expense" and r["cash_month"] == OPEN
                             and (r["category"] or "").startswith(DEBT_COST))),
}
with open(os.path.join(ROOT, "data", "dashboard.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("avg", "coverage", "debt_inflow_12m", "debt_cost_12m")}, ensure_ascii=False))
print(json.dumps(out["categories"], ensure_ascii=False))
for x in month_rows:
    print(x["month"], x["salary"], x["bonus13"], x["one_off"], x["reimbursement"], x["other"], "|", x["spend"], x["fixed"], x["essential"],
          x["discretionary"], x["gray"], x["refund"], "| debt", x["debt_inflow"], x["debt_cost"])
