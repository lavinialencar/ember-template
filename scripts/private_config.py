"""Loads and validates Ember's two personal files, which live in data/ (outside git):

  data/private_rules.json    classification rules that depend on who you are (name, document,
                             counterparties, splits). Used by classify.py and dashboard_data.py.
  data/manual_records.json   what the API does not bring: debts, receivables, points, cards, subscriptions.
                             Used by alerts.py and dashboard_data.py.

Templates with made-up data live in examples/. An invalid file stops everything with a clear message: it is
better to build no dashboard than to build a wrong one in silence.
"""

import json
import math
import os
import re
import unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

FLOW_TYPES = ("expense", "income", "one_off_income", "reimbursement", "debt_inflow", "neutral", "refund", "future_commitment")
ESSENTIALITIES = ("committed_fixed", "essential_variable", "discretionary", "mixed", "gray")
SCOPES = ("personal", "business")
TEXT_MAX = 200
LIST_MAX = 2000
SOURCE_OK = re.compile(r"^[a-z0-9_]{1,30}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DAY_MONTH = re.compile(r"^\d{2}/\d{2}(/\d{4})?$")


def norm(s):
    """Lowercase, no accents, collapsed spaces: the form every description is compared in."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


class InvalidConfig(ValueError):
    pass


def _error(where, msg):
    raise InvalidConfig(f"{where}: {msg}")


def _text(v, where, minimum=1, optional=False):
    if v is None and optional:
        return None
    if not isinstance(v, str) or not (minimum <= len(v) <= TEXT_MAX):
        _error(where, f"text of {minimum} to {TEXT_MAX} characters")
    return v


def _number(v, where, optional=True, minimum=None):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _error(where, "finite number")
    if minimum is not None and v < minimum:
        _error(where, f"number greater than or equal to {minimum}")
    return v


def _integer(v, where, minimum=0, maximum=None, optional=True):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum or (maximum is not None and v > maximum):
        _error(where, f"integer between {minimum} and {maximum if maximum is not None else 'infinity'}")
    return v


def _enum(v, options, where, default=None):
    if v is None:
        return default
    if v not in options:
        _error(where, "one of " + ", ".join(options))
    return v


def _list(v, where):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > LIST_MAX:
        _error(where, f"list with up to {LIST_MAX} items")
    return v


def _object(v, where, allowed):
    if not isinstance(v, dict):
        _error(where, "object")
    extra = set(v) - set(allowed)
    if extra:
        _error(where, "unknown key " + ", ".join(sorted(extra)) + " (check the spelling in the example)")
    return v


def _range(r, where):
    vmin = _number(r.get("amount_min"), where + ".amount_min")
    vmax = _number(r.get("amount_max"), where + ".amount_max")
    if vmin is not None and vmax is not None and vmin > vmax:
        _error(where, "amount_min greater than amount_max")
    return vmin, vmax


def _snippet(v, where):
    """Text snippet searched in the already normalized description (lowercase, no accents)."""
    t = _text(v, where, minimum=3)
    return norm(t).strip()


def validate_rules(obj):
    """Returns the normalized rules (snippets lowercase without accents, defaults filled in) or raises InvalidConfig."""
    _object(obj, "private_rules", ("owner", "neutral", "income", "patterns", "splits", "subscription_groups", "_comment"))
    owner = _object(obj.get("owner") or {}, "owner", ("document", "names"))
    doc = owner.get("document") or ""
    if not isinstance(doc, str) or not re.fullmatch(r"(\d{11}|\d{14})?", doc):
        _error("owner.document", "digits only: 11 (CPF) or 14 (CNPJ), or empty")
    names = [_snippet(n, f"owner.names[{i}]") for i, n in enumerate(_list(owner.get("names"), "owner.names"))]
    if any(len(n) < 4 for n in names):
        _error("owner.names", "each name needs 4+ letters (a short name would match any description)")
    out = {"owner": {"document": doc, "names": names}}
    out["neutral"] = [_snippet(n, f"neutral[{i}]") for i, n in enumerate(_list(obj.get("neutral"), "neutral"))]

    out["income"] = []
    for i, r in enumerate(_list(obj.get("income"), "income")):
        where = f"income[{i}]"
        _object(r, where, ("contains", "type", "category", "amount_min", "amount_max", "scope"))
        vmin, vmax = _range(r, where)
        out["income"].append({
            "contains": _snippet(r.get("contains"), where + ".contains"),
            "type": _enum(r.get("type"), ("income", "one_off_income", "reimbursement", "debt_inflow", "neutral", "refund"), where + ".type", "income"),
            "category": _text(r.get("category"), where + ".category"),
            "amount_min": vmin, "amount_max": vmax,
            "scope": _enum(r.get("scope"), SCOPES, where + ".scope", "personal"),
        })

    out["patterns"] = []
    for i, r in enumerate(_list(obj.get("patterns"), "patterns")):
        where = f"patterns[{i}]"
        _object(r, where, ("contains", "type", "category", "essentiality", "amount_min", "amount_max", "scope"))
        vmin, vmax = _range(r, where)
        ftype = _enum(r.get("type"), FLOW_TYPES, where + ".type", "expense")
        ess = _enum(r.get("essentiality"), ESSENTIALITIES, where + ".essentiality")
        if ftype == "expense" and ess is None:
            _error(where, "an expense needs an essentiality")
        out["patterns"].append({
            "contains": _snippet(r.get("contains"), where + ".contains"), "type": ftype,
            "category": _text(r.get("category"), where + ".category", optional=ftype != "expense"),
            "essentiality": ess, "amount_min": vmin, "amount_max": vmax,
            "scope": _enum(r.get("scope"), SCOPES, where + ".scope", "personal"),
        })

    out["splits"] = []
    for i, r in enumerate(_list(obj.get("splits"), "splits")):
        where = f"splits[{i}]"
        _object(r, where, ("contains", "amount_min", "amount_max", "parts"))
        vmin, vmax = _range(r, where)
        parts = []
        for j, p in enumerate(_list(r.get("parts"), where + ".parts")):
            wp = f"{where}.parts[{j}]"
            _object(p, wp, ("share", "type", "category", "essentiality", "scope"))
            share = _number(p.get("share"), wp + ".share", optional=False, minimum=0)
            ftype = _enum(p.get("type"), FLOW_TYPES, wp + ".type", "expense")
            ess = _enum(p.get("essentiality"), ESSENTIALITIES, wp + ".essentiality")
            if ftype == "expense" and ess is None:
                _error(wp, "an expense needs an essentiality")
            parts.append({"share": share, "type": ftype, "category": _text(p.get("category"), wp + ".category"),
                          "essentiality": ess, "scope": _enum(p.get("scope"), SCOPES, wp + ".scope", "personal")})
        if len(parts) < 2 or abs(sum(p["share"] for p in parts) - 1) > 0.001:
            _error(where, "parts: 2 or more, with shares adding up to 1")
        out["splits"].append({"contains": _snippet(r.get("contains"), where + ".contains"), "amount_min": vmin, "amount_max": vmax, "parts": parts})

    out["subscription_groups"] = []
    for i, r in enumerate(_list(obj.get("subscription_groups"), "subscription_groups")):
        where = f"subscription_groups[{i}]"
        _object(r, where, ("group", "contains", "only_amount", "exclude_amount", "sporadic"))
        spor = r.get("sporadic", False)
        if not isinstance(spor, bool):
            _error(where + ".sporadic", "true or false")
        out["subscription_groups"].append({
            "group": _text(r.get("group"), where + ".group"), "contains": _snippet(r.get("contains"), where + ".contains"),
            "only_amount": _number(r.get("only_amount"), where + ".only_amount"),
            "exclude_amount": _number(r.get("exclude_amount"), where + ".exclude_amount"),
            "sporadic": spor,
        })
    return out


def _date(v, where, optional=True):
    if v is None and optional:
        return None
    if not isinstance(v, str) or not ISO_DATE.fullmatch(v):
        _error(where, "date YYYY-MM-DD")
    return v


def _day_month(v, where):
    if v is None:
        return None
    if not isinstance(v, str) or not DAY_MONTH.fullmatch(v):
        _error(where, "date DD/MM or DD/MM/YYYY")
    return v


def validate_records(obj):
    """Returns the manual records with defaults filled in or raises InvalidConfig."""
    _object(obj, "manual_records", ("read_on", "cards", "debts", "receivables", "points", "subscriptions", "tax_receipts", "_comment"))
    out = {"read_on": _date(obj.get("read_on"), "read_on")}
    out["cards"] = []
    for i, c in enumerate(_list(obj.get("cards"), "cards")):
        where = f"cards[{i}]"
        _object(c, where, ("source", "name", "limit", "open_bill", "closes", "due", "last_rotation"))
        if not isinstance(c.get("source"), str) or not SOURCE_OK.fullmatch(c["source"]):
            _error(where + ".source", "label [a-z0-9_], the same as in PLUGGY_ITEM_IDS")
        out["cards"].append({
            "source": c["source"], "name": _text(c.get("name"), where + ".name"),
            "limit": _number(c.get("limit"), where + ".limit", minimum=0),
            "open_bill": _number(c.get("open_bill"), where + ".open_bill"),
            "closes": _integer(c.get("closes"), where + ".closes", 1, 28), "due": _integer(c.get("due"), where + ".due", 1, 28),
            "last_rotation": _date(c.get("last_rotation"), where + ".last_rotation"),
        })
    out["debts"] = []
    for i, d in enumerate(_list(obj.get("debts"), "debts")):
        where = f"debts[{i}]"
        _object(d, where, ("name", "type", "balance", "installment", "installments_total", "installments_paid", "next_due", "note"))
        item = {
            "name": _text(d.get("name"), where + ".name"), "type": _enum(d.get("type"), ("contract", "informal"), where + ".type", "contract"),
            "balance": _number(d.get("balance"), where + ".balance", minimum=0),
            "installment": _number(d.get("installment"), where + ".installment", minimum=0),
            "installments_total": _integer(d.get("installments_total"), where + ".installments_total", 1, 1000),
            "installments_paid": _integer(d.get("installments_paid"), where + ".installments_paid", 0, 1000) or 0,
            "next_due": _day_month(d.get("next_due"), where + ".next_due"), "note": _text(d.get("note"), where + ".note", 0, True) or "",
        }
        if item["balance"] is None and (item["installment"] is None or item["installments_total"] is None):
            _error(where, "set balance, or installment and installments_total")
        if item["installments_total"] is not None and item["installments_paid"] > item["installments_total"]:
            _error(where, "installments_paid greater than installments_total")
        out["debts"].append(item)
    out["receivables"] = []
    for i, r in enumerate(_list(obj.get("receivables"), "receivables")):
        where = f"receivables[{i}]"
        _object(r, where, ("name", "installment", "installments_total", "received", "note"))
        rec = [_day_month(x, f"{where}.received[{j}]") for j, x in enumerate(_list(r.get("received"), where + ".received"))]
        total = _integer(r.get("installments_total"), where + ".installments_total", 1, 1000, optional=False)
        if len(rec) > total:
            _error(where, "more received than installments_total")
        out["receivables"].append({"name": _text(r.get("name"), where + ".name"), "installment": _number(r.get("installment"), where + ".installment", False, 0),
                                   "installments_total": total, "received": rec, "note": _text(r.get("note"), where + ".note", 0, True) or ""})
    out["points"] = []
    for i, p in enumerate(_list(obj.get("points"), "points")):
        where = f"points[{i}]"
        _object(p, where, ("program", "pts", "brl", "expires", "note"))
        out["points"].append({"program": _text(p.get("program"), where + ".program"), "pts": _number(p.get("pts"), where + ".pts", minimum=0),
                              "brl": _number(p.get("brl"), where + ".brl", minimum=0), "expires": _day_month(p.get("expires"), where + ".expires"),
                              "note": _text(p.get("note"), where + ".note", 0, True) or ""})
    out["subscriptions"] = []
    for i, a in enumerate(_list(obj.get("subscriptions"), "subscriptions")):
        where = f"subscriptions[{i}]"
        _object(a, where, ("name", "contains", "amount", "monthly", "only_amount", "detail"))
        monthly = a.get("monthly", True)
        if not isinstance(monthly, bool):
            _error(where + ".monthly", "true or false")
        out["subscriptions"].append({"name": _text(a.get("name"), where + ".name"), "contains": _snippet(a.get("contains"), where + ".contains"),
                                     "amount": _number(a.get("amount"), where + ".amount", minimum=0), "monthly": monthly,
                                     "only_amount": _number(a.get("only_amount"), where + ".only_amount"),
                                     "detail": _text(a.get("detail"), where + ".detail", 0, True) or ""})
    tr = obj.get("tax_receipts")
    out["tax_receipts"] = None
    if tr is not None:
        _object(tr, "tax_receipts", ("tax_deadline", "items"))
        items = []
        for i, it in enumerate(_list(tr.get("items"), "tax_receipts.items")):
            where = f"tax_receipts.items[{i}]"
            _object(it, where, ("description", "has_receipt", "auto_uploaded"))
            if not isinstance(it.get("has_receipt"), bool) or not isinstance(it.get("auto_uploaded", False), bool):
                _error(where, "has_receipt and auto_uploaded are true or false")
            items.append({"description": _text(it.get("description"), where + ".description"), "has_receipt": it["has_receipt"],
                          "auto_uploaded": it.get("auto_uploaded", False)})
        out["tax_receipts"] = {"tax_deadline": _date(tr.get("tax_deadline"), "tax_receipts.tax_deadline", optional=False), "items": items}
    return out


def _load(name, validate, example):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        raise SystemExit(f"Missing data/{name}. Copy examples/{example} to data/{name} and fill it in with your own data.")
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except ValueError as e:
        raise SystemExit(f"data/{name} is not valid JSON: {e}")
    try:
        return validate(obj)
    except InvalidConfig as e:
        raise SystemExit(f"data/{name} is invalid at {e}")


def load_rules():
    return _load("private_rules.json", validate_rules, "private_rules.example.json")


def load_records():
    return _load("manual_records.json", validate_records, "manual_records.example.json")
