#!/usr/bin/env python3
"""Fetches the credit card bills (GET /bills) and writes them to data/bills.json.

Used for the card's cash month: the bill due date says when the money leaves,
not the purchase date. data/ stays outside git. Authenticates from scratch (the apiKey lasts 2h).
"""

import json
import os

from fetch_history import API_BASE, ROOT, call, load_env, pluggy_items


def main():
    env = load_env()
    items = pluggy_items(env.get("PLUGGY_ITEM_IDS"))  # validate before spending an API call
    api_key = call(
        f"{API_BASE}/auth",
        method="POST",
        body={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]},
    )["apiKey"]

    bills = []
    for source, item_id in items.items():
        accounts = call(f"{API_BASE}/accounts?itemId={item_id}", api_key=api_key)
        for account in accounts.get("results", []):
            if account.get("type") != "CREDIT":
                continue
            page = call(f"{API_BASE}/bills?accountId={account['id']}&pageSize=500", api_key=api_key)
            for b in page.get("results", []):
                b["_source"] = source
                b["_account_name"] = account.get("name")
                bills.append(b)
            print(f"{source} {account.get('name')}: {len(page.get('results', []))} bills")

    with open(os.path.join(ROOT, "data", "bills.json"), "w", encoding="utf-8") as f:
        json.dump(bills, f, ensure_ascii=False, indent=1)
    print(f"{len(bills)} bills written to data/bills.json")


if __name__ == "__main__":
    os.umask(0o077)
    main()
