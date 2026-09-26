#!/usr/bin/env python3
"""Fetches the full history (12 months) of each connected bank and writes it to data/transactions.json.

data/ stays outside git (financial data). Run it again whenever you want to refresh.
The apiKey lasts 2h, so the script authenticates from scratch every time.
Which connections to fetch comes from PLUGGY_ITEM_IDS in .env (or the environment): "source:itemId,source:itemId".
"""

import json
import math
import os
import re
import urllib.request

API_BASE = "https://api.pluggy.ai"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SOURCE_OK = re.compile(r"^[a-z0-9_]{1,30}$")
UUID_OK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def load_env():
    """Reads .env (if present); an environment variable with the same name wins (useful in the container and in CI)."""
    values = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"')
    for key in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def pluggy_items(text):
    """'banco_a:<uuid>,banco_b:<uuid>' -> {'banco_a': '<uuid>', ...}. source is the label shown in the dashboard and in
    the rules ([a-z0-9_], up to 30); itemId is the connection UUID at Pluggy (MeuPluggy). Anything else stops everything."""
    items = {}
    for pair in (text or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        source, sep, item_id = pair.partition(":")
        source, item_id = source.strip(), item_id.strip().lower()
        if not sep or not SOURCE_OK.fullmatch(source):
            raise ValueError(f"PLUGGY_ITEM_IDS: invalid label in '{source[:40]}' (use a-z, 0-9 and _, up to 30)")
        if not UUID_OK.fullmatch(item_id):
            raise ValueError(f"PLUGGY_ITEM_IDS: itemId of '{source}' is not a UUID")
        if source in items:
            raise ValueError(f"PLUGGY_ITEM_IDS: label '{source}' repeated")
        items[source] = item_id
    if not items:
        raise ValueError("PLUGGY_ITEM_IDS is empty: set it in .env, e.g. banco_a:<itemId>,banco_b:<itemId>")
    return items


def call(url, api_key=None, method="GET", body=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


NEXT_OK = re.compile(r"^\?[A-Za-z0-9=&_%.-]+$")


def next_page(nxt):
    """URL of the next page of /v2/transactions, or None. Pluggy's "next" is just a query string;
    anything else (another host, a path, an odd character) ends pagination with a warning."""
    if not nxt:
        return None
    if not isinstance(nxt, str) or not NEXT_OK.fullmatch(nxt):
        print("warning: Pluggy 'next' not in the expected format; pagination stopped for this account")
        return None
    return f"{API_BASE}/v2/transactions{nxt}"


def transaction_ok(t):
    """Minimal check of what comes from the API: id and date are text, amount is a finite number."""
    return (isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("date"), str)
            and isinstance(t.get("amount"), (int, float)) and not isinstance(t.get("amount"), bool)
            and math.isfinite(t["amount"]))


def only_valid(res):
    good = [t for t in res if transaction_ok(t)]
    if len(good) != len(res):
        print(f"warning: {len(res) - len(good)} malformed transactions ignored")
    return good


def main():
    env = load_env()
    items = pluggy_items(env.get("PLUGGY_ITEM_IDS"))  # validate before spending an API call
    api_key = call(
        f"{API_BASE}/auth",
        method="POST",
        body={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]},
    )["apiKey"]

    everything = []
    for source, item_id in items.items():
        accounts = call(f"{API_BASE}/accounts?itemId={item_id}", api_key=api_key)
        for account in accounts.get("results", []):
            url = f"{API_BASE}/v2/transactions?accountId={account['id']}"
            while url:
                page = call(url, api_key=api_key)
                for t in only_valid(page.get("results", [])):
                    t["_source"] = source
                    t["_account_name"] = account.get("name")
                    t["_account_type"] = account.get("type")
                    everything.append(t)
                # "next" is the whole query string of the next page, not a token
                url = next_page(page.get("next"))
        print(f"{source}: ok")

    dest = os.path.join(ROOT, "data", "transactions.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(everything, f, ensure_ascii=False)
    print(f"{len(everything)} transactions written to {dest}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
