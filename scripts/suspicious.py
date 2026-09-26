"""Odd card purchase detector. Used by alerts.py; also runs on its own for a retroactive test.

Only looks at credit card purchases (DEBIT on a CREDIT account). Compares each recent purchase with earlier purchases
in the same history: no fixed amount rule, the pattern is the owner's own. Signals:
  international        currency other than BRL, or a country at the end of the description other than BR/BRA
  new category         merchant category code (MCC) never seen before, on a purchase of R$ 50 or more
  burst                3 or more different merchants within 10 minutes
  new and expensive    merchant never seen, with an amount above the history's 95th percentile and above R$ 300
City is left out: online purchases often come with the city of the store's head office, so city causes false alarms.
The "It was me" button (known) makes that purchase's category and merchant stop counting as new.
"""

import os
import re
import unicodedata
from datetime import datetime, timedelta

COUNTRIES_OK = {"BR", "BRA"}


def no_time_hour():
    """A bank entry with no time comes as local midnight converted to UTC. Time zone from EMBER_TZ
    (default America/Sao_Paulo, where that gives 03:00:00)."""
    try:
        from zoneinfo import ZoneInfo
        off = datetime.now(ZoneInfo(os.environ.get("EMBER_TZ") or "America/Sao_Paulo")).utcoffset()
        return (datetime(2000, 1, 2) - off).strftime("%H:%M:%S")
    except Exception:  # no time zone database on the system: all of Brazil without daylight saving is at or near UTC-3
        return "03:00:00"


NO_TIME_HOUR = no_time_hour()


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def merchant(desc):
    # strips Portuguese filler words that banks put in descriptions
    n = re.sub(r"\b(pix|compra|debito|credito|pagamento|de|da|do|em|parc|cp|mp|pg|pagto)\b", " ", re.sub(r"[^a-z ]", " ", norm(desc)))
    return " ".join(n.split()[:2])


def mcc(x):
    return (x.get("creditCardMetadata") or {}).get("payeeMCC")


def when(x):
    return datetime.fromisoformat(x["date"].replace("Z", "+00:00")).replace(tzinfo=None)


def card_purchases(trans):
    """A real purchase: credit card, outgoing, with a merchant category code (interest, IOF, fees and charges have none) and
    not a later installment of an old purchase."""
    out = []
    for x in trans:
        md = x.get("creditCardMetadata") or {}
        if x.get("_account_type") == "CREDIT" and x["type"] == "DEBIT" and md.get("payeeMCC") and (md.get("installmentNumber") or 1) == 1:
            out.append(x)
    return out


def has_time(x):
    """An entry with no time (local midnight in UTC): for it, "a few minutes" means nothing."""
    return when(x).strftime("%H:%M:%S") != NO_TIME_HOUR


def analyze(trans, start, end, known_mcc=(), known_merchants=()):
    """Purchases dated in [start, end] (dates) that break the pattern before start. Returns a list of dicts."""
    purchases = card_purchases(trans)
    before = [x for x in purchases if when(x).date() < start]
    if len(before) < 200:  # without history "new" means nothing
        return []
    mccs = {mcc(x) for x in before if mcc(x)} | set(known_mcc)
    merchants = {merchant(x["description"]) for x in before} | set(known_merchants)
    amounts = sorted(abs(x["amount"]) for x in before)
    p95 = amounts[int(len(amounts) * 0.95)]
    window = [x for x in purchases if start <= when(x).date() <= end]
    found = []
    for x in window:
        reasons = []
        desc = (x.get("descriptionRaw") or x["description"] or "").upper().strip()
        country = re.search(r"\b([A-Z]{2,3})$", desc)
        if (x.get("currencyCode") or "BRL") != "BRL" or (country and country.group(1) not in COUNTRIES_OK and len(country.group(1)) == 3 and country.group(1) not in ("LTD", "COM", "APP", "LTDA")):
            reasons.append("international purchase")
        if mcc(x) and mcc(x) not in mccs and abs(x["amount"]) >= 50:  # a new category for pocket change is almost always legit
            reasons.append("merchant category never seen")
        m = merchant(x["description"])
        if m and m not in merchants and abs(x["amount"]) > max(300, p95):
            reasons.append("new merchant with a high amount")
        near = [y for y in window if has_time(y) and has_time(x) and abs((when(y) - when(x)).total_seconds()) <= 600]
        if len({merchant(y["description"]) for y in near}) >= 3:
            reasons.append("several purchases within minutes")
        if reasons:
            found.append({"id": x["id"], "date": x["date"], "merchant": m or desc[:30], "amount": abs(x["amount"]),
                          "card": x.get("_source"), "mcc": mcc(x), "reasons": reasons})
    return found


if __name__ == "__main__":  # retroactive test: how many alerts it would have raised in the last 120 days
    import json
    from collections import Counter
    from datetime import date
    ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    t = json.load(open(os.path.join(ROOT, "data", "transactions.json"), encoding="utf-8"))
    end_total = date.today()  # the statement has future installments: do not use the latest date
    seen, by_reason = {}, Counter()
    for d in range(120, -1, -1):
        day = end_total - timedelta(days=d)
        upto = [x for x in t if when(x).date() <= day]
        for a in analyze(upto, day - timedelta(days=2), day):
            if a["id"] not in seen:
                seen[a["id"]] = a
                for r in a["reasons"]:
                    by_reason[r] += 1
    print(f"{len(seen)} purchases flagged in 120 days:", dict(by_reason))
    for a in sorted(seen.values(), key=lambda a: a["date"])[-25:]:
        print(a["date"][:16], a["card"], a["merchant"][:28].ljust(28), round(a["amount"]), "|", "; ".join(a["reasons"]))
