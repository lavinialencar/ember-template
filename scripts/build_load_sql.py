#!/usr/bin/env python3
"""Builds data/load.sql: the classified flow, the bills and the card limits, ready for Postgres (migration 0004).

Reads data/flow.json, data/bills.json and data/accounts.json (which update.py already writes) and writes
INSERT ... ON CONFLICT DO UPDATE, so running it again does not duplicate. Plain SQL only, no dependency:
  psql -h <server> -U ember -d ember -f data/load.sql
It lives in data/ because it has financial data (outside git).

Usage: python3 build_load_sql.py
"""

import json
import math
import os
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read(name):
    path = os.path.join(ROOT, "data", name)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []


def q(v):
    """SQL literal: NULL, number, boolean or text (E'' with quotes and backslashes escaped,
    so it does not depend on Postgres standard_conforming_strings). A Pix description comes from
    whoever sends the money, so it is outside text and needs robust escaping.
    The right way would be a parameterized query, but that needs a driver (psycopg) and Ember is stdlib only with
    psql; so the text is escaped here, the NUL byte is dropped (Postgres does not accept NUL in text) and
    numbers must be finite (NaN and Infinity raise an error, never SQL)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            raise ValueError("non-finite number in the load")
        return repr(v)
    text = str(v).replace("\x00", "").replace("\\", "\\\\").replace("'", "''")
    return "E'" + text + "'"


def upsert(table, columns, key, rows):
    """key: one column or several separated by commas."""
    if not rows:
        return []
    keys = [c.strip() for c in key.split(",")]
    update = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in keys)
    return [f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(q(v) for v in r)}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {update};" for r in rows]


def main():
    flow, bills, accounts = read("flow.json"), read("bills.json"), read("accounts.json")
    sql = [f"-- Ember, load built on {date.today().isoformat()}: {len(flow)} flow rows, {len(bills)} bills.", "BEGIN;"]

    cols = ["id", "part", "date", "cash_month", "source", "account", "description", "amount", "category", "essentiality",
            "scope", "reason", "pluggy_category", "card", "flow_type"]
    seen = {}
    for r in flow:  # the same transaction on more than one row becomes part 0, 1, ...
        r["_part"] = seen.get(r["id"], 0)
        seen[r["id"]] = r["_part"] + 1
    sql += upsert("mart.flow", cols, "id, part", [
        [r["id"], r["_part"], r["date"], r["cash_month"], r["source"], r.get("account"), r.get("description"), r["amount"], r.get("category"),
         r.get("essentiality"), r.get("scope"), r.get("reason"), r.get("pluggy_category"), bool(r.get("card")), r["flow_type"]] for r in flow])

    cols = ["id", "source", "due_date", "closing_date", "total", "minimum_payment", "allows_installments", "finance_charges"]
    sql += upsert("mart.bill", cols, "id", [
        [b["id"], b["_source"], b["dueDate"][:10], (b.get("billClosingDate") or "")[:10] or None, b["totalAmount"],
         b.get("minimumPaymentAmount"), b.get("allowsInstallments"), round(sum(c["amount"] for c in b.get("financeCharges") or []), 2)]
        for b in bills])

    cols = ["account_id", "source", "name", "credit_limit", "available", "minimum_payment", "due_date", "read_on"]
    sql += upsert("mart.card_limit", cols, "account_id", [
        [c["id"], c["source"], c.get("name"), c["credit"].get("creditLimit"), c["credit"].get("availableCreditLimit"),
         c["credit"].get("minimumPayment"), (c["credit"].get("balanceDueDate") or "")[:10] or None, c["updated"]]
        for c in accounts if c.get("type") == "CREDIT" and c.get("credit")])

    sql.append("COMMIT;")
    path = os.path.join(ROOT, "data", "load.sql")
    open(path, "w", encoding="utf-8").write("\n".join(sql) + "\n")
    print(f"load.sql: {len(sql) - 3} statements ({len(flow)} flow, {len(bills)} bills)")


if __name__ == "__main__":
    os.umask(0o077)
    main()
