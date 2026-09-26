#!/usr/bin/env python3
"""Looks up the CNAE (business activity code) of each CNPJ (company taxpayer ID) found in the gray zone and writes rules per document.

Sends only the CNPJ of a COMPANY (public data) to BrasilAPI. The result goes to
data/cnpj_cache.json and data/cnpj_rules.json (outside git). classify.py reads the rules.
Run it after fetch_history.py and classify.py; run classify.py again at the end.
"""

import json
import os
import re
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
API = "https://brasilapi.com.br/api/cnpj/v1/"

# CNAE (first 2 or 4 digits) -> (category, essentiality). The most specific wins.
CNAE = {
    "5611": ("Eating out", "discretionary"), "5612": ("Eating out", "discretionary"),
    "5620": ("Eating out", "discretionary"), "56": ("Eating out", "discretionary"),
    "4711": ("Groceries", "essential_variable"), "4712": ("Groceries", "essential_variable"),
    "4721": ("Groceries", "essential_variable"), "4722": ("Groceries", "essential_variable"),
    "4723": ("Groceries", "essential_variable"), "4724": ("Groceries", "essential_variable"),
    "4729": ("Groceries", "essential_variable"),
    "4771": ("Pharmacy", "essential_variable"), "4772": ("Personal care", "discretionary"),
    "4781": ("Clothing and shoes", "discretionary"), "4782": ("Clothing and shoes", "discretionary"),
    "4783": ("Clothing and shoes", "discretionary"),
    "4751": ("Electronics and computers", "discretionary"), "4752": ("Electronics and computers", "discretionary"),
    "4753": ("Electronics and computers", "discretionary"), "4754": ("Home and moving", "essential_variable"),
    "4755": ("Home and moving", "essential_variable"), "4756": ("Home and moving", "essential_variable"),
    "4757": ("Home and moving", "essential_variable"), "4759": ("Home and moving", "essential_variable"),
    "4741": ("Housing, maintenance", "essential_variable"), "4742": ("Housing, maintenance", "essential_variable"),
    "4744": ("Housing, maintenance", "essential_variable"), "4761": ("Books and stationery", "discretionary"),
    "4762": ("Books and stationery", "discretionary"), "4763": ("Leisure", "discretionary"),
    "47": ("Shopping (marketplace)", "mixed"),
    "86": ("Health", "essential_variable"), "9602": ("Personal care", "discretionary"),
    "93": ("Leisure", "discretionary"), "90": ("Leisure", "discretionary"), "5914": ("Leisure", "discretionary"),
    "55": ("Travel", "discretionary"), "79": ("Travel", "discretionary"),
    "4923": ("Transport", "essential_variable"), "4921": ("Transport", "essential_variable"),
    "85": ("Education", "discretionary"), "62": ("Software and digital services", "discretionary"),
    "63": ("Software and digital services", "discretionary"),
    "5091": ("Transport", "essential_variable"), "5099": ("Transport", "essential_variable"),
    "9529": ("Housing, maintenance", "essential_variable"), "7420": ("Leisure", "discretionary"),
    "41": ("Housing, maintenance", "essential_variable"), "43": ("Housing, maintenance", "essential_variable"),
}


def only_digits(v):
    return re.sub(r"\D", "", v or "")


def map_cnae(cnae):
    c = str(cnae)
    if not c.isascii() or not c.isdigit():  # cnae_fiscal comes from BrasilAPI: only digits become a rule
        return None
    for n in (4, 2):
        if c[:n] in CNAE:
            return CNAE[c[:n]]
    return None


def main():
    t = json.load(open(os.path.join(ROOT, "data", "transactions.json"), encoding="utf-8"))
    flow_path = os.path.join(ROOT, "data", "flow.json")
    if not os.path.exists(flow_path):  # first run: there is no flow yet, so no gray zone to look up
        print("no data/flow.json yet, CNPJ lookup waits for the next run")
        return
    flow = json.load(open(flow_path, encoding="utf-8"))
    by_id = {x["id"]: x for x in t}
    cnpjs = set()
    for r in flow:
        if r["flow_type"] != "expense" or r["essentiality"] != "gray":
            continue
        x = by_id[r["id"]]
        d = (((x.get("paymentData") or {}).get("receiver") or {}).get("documentNumber") or {})
        c = only_digits((x.get("merchant") or {}).get("cnpj")) or (only_digits(d.get("value")) if d.get("type") == "CNPJ" else "")
        if len(c) == 14:
            cnpjs.add(c)

    cache_path = os.path.join(ROOT, "data", "cnpj_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    pending = (cnpjs - set(cache)) | {c for c, v in cache.items() if "error" in v}
    for c in sorted(pending):
        try:
            req = urllib.request.Request(API + c, headers={"User-Agent": "ember-personal/1.0 (public CNPJ lookup)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.loads(resp.read())
            cache[c] = {k: d.get(k) for k in ("razao_social", "nome_fantasia", "cnae_fiscal", "cnae_fiscal_descricao", "municipio", "uf")}
        except Exception as e:  # noqa: BLE001
            cache[c] = {"error": str(e)[:80]}
        time.sleep(0.4)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    rules, unmapped = {}, []
    for c, d in cache.items():
        m = map_cnae(d.get("cnae_fiscal")) if d.get("cnae_fiscal") else None
        if m:
            rules[c] = {"category": m[0], "essentiality": m[1], "cnae": d["cnae_fiscal"], "desc": d.get("cnae_fiscal_descricao"), "company": d.get("razao_social")}
        else:
            unmapped.append((c, d.get("razao_social"), d.get("cnae_fiscal_descricao")))
    json.dump(rules, open(os.path.join(ROOT, "data", "cnpj_rules.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(cnpjs)} CNPJs in the gray zone, {len(rules)} became rules, {len(unmapped)} with no CNAE mapping")
    for c, name, desc in unmapped[:15]:
        print("  no mapping:", name, "|", desc)


if __name__ == "__main__":
    os.umask(0o077)
    main()
