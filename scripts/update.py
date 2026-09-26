#!/usr/bin/env python3
"""Updates all of Ember in one go, without burning through the Pluggy API quota.

Steps: fetches only what is new (recent window and future installments) and the connection status and merges it
into the local base, fetches the bills, looks up new CNPJs, runs the classification and the alerts, sends the push
(ntfy), builds data/dashboard.html and makes the encrypted backup (BACKUP_DEST).
The API returns newest first; so the window is replaced as a whole (a transaction's id
can change when it stops being PENDING), with no duplicates.

Usage: python3 update.py                (runs everything)
       python3 update.py --no-api       (only redoes classification and dashboard with what is already in data/)
       python3 update.py --no-push      (sends no push and reads no ntfy replies)
       python3 update.py --no-backup    (writes no backup)
Demo, fully offline: python3 scripts/make_demo.py && python3 scripts/update.py --no-api --no-push --no-backup
Output: data/dashboard.html (outside git; it has financial data).
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta

from fetch_history import API_BASE, ROOT, call, load_env, next_page, only_valid, pluggy_items

WINDOW_DAYS = 25  # what Pluggy can still change (PENDING becomes POSTED)
HERE = os.path.dirname(os.path.abspath(__file__))
FLAGS = ("--no-api", "--no-push", "--no-backup")


def fetch_new():
    path = os.path.join(ROOT, "data", "transactions.json")
    base = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    shutil.copy(path, path.replace(".json", ".before.json")) if os.path.exists(path) else None
    cutoff = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()
    env = load_env()
    items = pluggy_items(env.get("PLUGGY_ITEM_IDS"))
    key = call(f"{API_BASE}/auth", method="POST", body={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]})["apiKey"]
    calls, new = 0, 0
    status = {}
    all_accounts = []
    for source, item_id in items.items():
        it = call(f"{API_BASE}/items/{item_id}", api_key=key)
        calls += 1
        status[source] = {k: it.get(k) for k in ("status", "executionStatus", "lastUpdatedAt")}
        accounts = call(f"{API_BASE}/accounts?itemId={item_id}", api_key=key)
        calls += 1
        for account in accounts.get("results", []):
            account_id = account["id"]
            all_accounts.append({"source": source, "id": account_id, "name": account.get("name"), "type": account.get("type"),
                                 "credit": account.get("creditData") or None, "updated": date.today().isoformat()})
            known = any(x["accountId"] == account_id for x in base)
            received, url, incomplete = [], f"{API_BASE}/v2/transactions?accountId={account_id}", False
            while url:
                page = call(url, api_key=key)
                calls += 1
                res = only_valid(page.get("results", []))
                for x in res:
                    x["_source"], x["_account_name"], x["_account_type"] = source, account.get("name"), account.get("type")
                received.extend(res)
                # order: newest first. For a known account, stop when the whole page
                # is older than the window (future installments come first and are walked through).
                if known and res and max((x.get("date") or "")[:10] for x in res) < cutoff:
                    break
                url = next_page(page.get("next"))
                incomplete = bool(page.get("next")) and url is None
            if known and incomplete:  # pagination cut short: replacing the window would drop what did not come; keep the old base
                print("warning: account with incomplete pagination, window kept as it was")
            elif known:
                base = [x for x in base if not (x["accountId"] == account_id and ((x.get("date") or "")[:10] >= cutoff))]
                new_here = [x for x in received if (x.get("date") or "")[:10] >= cutoff]
                base.extend(new_here)
                new += len(new_here)
            else:
                base.extend(received)
                new += len(received)
    with open(os.path.join(ROOT, "data", "accounts.json"), "w", encoding="utf-8") as f:
        json.dump(all_accounts, f, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "data", "items.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False)
    print(f"API: {calls} calls, base with {len(base)} transactions")


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
    print(f"{script}: {'ok' if r.returncode == 0 else 'ERROR'}")
    if r.returncode != 0:
        print(r.stderr[-800:])
        raise SystemExit(1)


def run_optional(script, *args):
    """A step that must not bring down the rest (e.g. push with no internet)."""
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True)
    print(f"{script}: {'ok' if r.returncode == 0 else 'failed, continuing without it'}")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr[-400:])


def main():
    os.umask(0o077)  # everything Ember creates in data/ (and the child scripts, which inherit it) is owner-only
    unknown = [a for a in sys.argv[1:] if a not in FLAGS]
    if unknown:
        raise SystemExit("unknown option: " + " ".join(unknown))
    if "--no-api" not in sys.argv:
        fetch_new()
        run("fetch_bills.py")
        run("enrich_cnpj.py")
    run("classify.py")
    run("alerts.py")
    if "--no-push" not in sys.argv:
        run_optional("notify.py")
    run("dashboard_data.py")
    run("dashboard_build.py")
    if "--no-backup" not in sys.argv:
        run("backup.py")
    print("done: data/dashboard.html")


if __name__ == "__main__":
    main()
