import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _base  # noqa: F401  (puts scripts/ on the path)
import classify
import fetch_history as fh
import private_config as pc

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EX = os.path.join(ROOT, "examples")
A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"


def example(name):
    with open(os.path.join(EX, name), encoding="utf-8") as f:
        return json.load(f)


class PluggyItems(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(fh.pluggy_items(f"banco_a:{A}, banco_b : {B.upper()} ,"), {"banco_a": A, "banco_b": B})

    def test_invalid(self):
        for bad in (None, "", " , ", f"Banco:{A}", f"banco-a:{A}", f"{'x' * 31}:{A}", "banco_a:123", f"banco_a{A}",
                    f"banco_a:{A},banco_a:{B}", f"banco_a:{A}x", f"banco_a:../{A}", f"banco_a:{A}\nb:{B}"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                fh.pluggy_items(bad)

    def test_env_wins_over_file(self):
        old = os.environ.get("PLUGGY_ITEM_IDS")
        os.environ["PLUGGY_ITEM_IDS"] = f"banco_x:{A}"
        try:
            self.assertEqual(fh.load_env()["PLUGGY_ITEM_IDS"], f"banco_x:{A}")
        finally:
            if old is None:
                del os.environ["PLUGGY_ITEM_IDS"]
            else:
                os.environ["PLUGGY_ITEM_IDS"] = old


class PrivateRules(unittest.TestCase):
    def test_example_valid_and_normalized(self):
        r = pc.validate_rules(example("private_rules.example.json"))
        self.assertEqual(r["owner"]["document"], "12345678900")
        self.assertTrue(all(p["scope"] in ("personal", "business") for p in r["patterns"]))
        obj = example("private_rules.example.json")
        obj["patterns"][0]["contains"] = "ACADEMIA  Exémplo"
        self.assertEqual(pc.validate_rules(obj)["patterns"][0]["contains"], "academia exemplo")

    def test_refuses(self):
        base = example("private_rules.example.json")
        breakages = [
            lambda o: o.update(new_key=1),
            lambda o: o["owner"].update(document="123.456.789-00"),
            lambda o: o["owner"].update(names=["ana"]),
            lambda o: o["patterns"][0].update(essentiality="luxury"),
            lambda o: o["patterns"][0].pop("essentiality"),
            lambda o: o["patterns"][0].update(contains="ab"),
            lambda o: o["patterns"][0].update(contains="x" * 201),
            lambda o: o["patterns"][0].update(amount_min=10, amount_max=5),
            lambda o: o["patterns"][0].update(amount_min=float("nan")),
            lambda o: o["patterns"][0].update(scope="company"),
            lambda o: o["income"][0].update(type="expense"),
            lambda o: o["splits"][0]["parts"][0].update(share=0.7),
            lambda o: o["splits"][0]["parts"].pop(),
            lambda o: o["subscription_groups"][0].update(sporadic="yes"),
            lambda o: o.update(patterns={"contains": "x"}),
            lambda o: o.update(neutral=["x"] * (pc.LIST_MAX + 1)),
        ]
        for i, breakage in enumerate(breakages):
            o = copy.deepcopy(base)
            breakage(o)
            with self.assertRaises(pc.InvalidConfig, msg=f"breakage {i}"):
                pc.validate_rules(o)

    def test_records_example_and_refusals(self):
        base = example("manual_records.example.json")
        c = pc.validate_records(base)
        self.assertEqual(c["debts"][2]["type"], "informal")
        for breakage in (lambda o: o["cards"][0].update(source="Banco A"), lambda o: o["cards"][0].update(closes=31),
                         lambda o: o["debts"][0].update(installments_paid=99), lambda o: o["debts"][1].pop("balance"),
                         lambda o: o["receivables"][0].update(received=["2026-06-21"]), lambda o: o.update(read_on="yesterday"),
                         lambda o: o["points"][0].update(pts=-1), lambda o: o.update(old_field={})):
            o = copy.deepcopy(base)
            breakage(o)
            with self.assertRaises(pc.InvalidConfig):
                pc.validate_records(o)


def tx(ttype, desc, payer=None, receiver=None, account="BANK"):
    t = {"id": "t1", "date": "2020-01-10T03:00:00.000Z", "amount": -100.0 if ttype == "DEBIT" else 100.0, "type": ttype,
         "description": desc, "category": None, "_source": "banco_a", "_account_name": "Account", "_account_type": account}
    if payer or receiver:
        t["paymentData"] = {k: {"name": v[0], "documentNumber": {"value": v[1]}} for k, v in (("payer", payer), ("receiver", receiver)) if v}
    return t


class SelfTransfer(unittest.TestCase):
    def ctx(self, **owner):
        rules = pc.validate_rules({"owner": owner})
        return {"rules": rules, "docs": {}, "cash": lambda t: t["date"][:7], "open": {}, "cnpj_rules": {}}

    def kind(self, t, ctx):
        r = classify.classify(t, ctx)[0]
        return r["flow_type"], r["reason"]

    def test_by_document(self):
        ctx = self.ctx(document="12345678900", names=[])
        me, other = ("Any Name", "12345678900"), ("Someone Else", "98765432101")
        self.assertEqual(self.kind(tx("DEBIT", "PIX ENVIADO", me, me), ctx)[0], "neutral")
        self.assertEqual(self.kind(tx("DEBIT", "PIX ENVIADO", None, me), ctx)[0], "neutral")
        self.assertEqual(self.kind(tx("CREDIT", "PIX RECEBIDO", me), ctx)[0], "neutral")
        self.assertNotEqual(self.kind(tx("DEBIT", "PIX ENVIADO", me, other), ctx)[0], "neutral")
        self.assertNotEqual(self.kind(tx("CREDIT", "PIX RECEBIDO", other), ctx)[0], "neutral")

    def test_by_name_when_document_missing(self):
        ctx = self.ctx(document="", names=["Fulana Exemplo"])
        self.assertEqual(self.kind(tx("CREDIT", "PIX RECEBIDO FULANA EXEMPLO"), ctx)[0], "neutral")
        self.assertEqual(self.kind(tx("DEBIT", "Transferencia para Fulána Exemplo"), ctx)[0], "neutral")
        self.assertNotEqual(self.kind(tx("CREDIT", "PIX RECEBIDO BELTRANO"), ctx)[0], "neutral")

    def test_no_config_does_not_guess(self):
        ctx = self.ctx()
        self.assertEqual(self.kind(tx("CREDIT", "PIX RECEBIDO FULANA EXEMPLO", ("F", "12345678900")), ctx),
                         ("income", "income with no rule"))

    def test_split_and_personal_rule(self):
        rules = pc.validate_rules(example("private_rules.example.json"))
        ctx = {"rules": rules, "docs": {}, "cash": lambda t: t["date"][:7], "open": {}, "cnpj_rules": {}}
        rows = classify.classify(tx("DEBIT", "PIX ENVIADO IMOBILIARIA EXEMPLO"), ctx)
        self.assertEqual([(r["flow_type"], r["amount"]) for r in rows], [("expense", 50.0), ("neutral", 50.0)])
        r = classify.classify(tx("DEBIT", "GRAFICA MODELO", account="CREDIT"), ctx)[0]
        self.assertEqual((r["category"], r["scope"]), ("Work supplies", "business"))


class Demo(unittest.TestCase):
    def test_demo_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            for folder in ("scripts", "examples"):
                shutil.copytree(os.path.join(ROOT, folder), os.path.join(tmp, folder), ignore=shutil.ignore_patterns("__pycache__"))
            env = {k: v for k, v in os.environ.items() if not k.startswith(("PLUGGY_", "NTFY_", "ALERT_", "BACKUP_"))}
            for cmd in (["make_demo.py"], ["update.py", "--no-api", "--no-push", "--no-backup"]):
                r = subprocess.run([sys.executable, os.path.join(tmp, "scripts", cmd[0]), *cmd[1:]], cwd=tmp, env=env,
                                   capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            dashboard = os.path.join(tmp, "data", "dashboard.html")
            self.assertTrue(os.path.exists(dashboard))
            html = open(dashboard, encoding="utf-8").read()
            self.assertNotIn("__DATA__", html)
            self.assertNotIn("__CSP_SCRIPT_HASH__", html)
            self.assertIn("Groceries", html)
            self.assertFalse(os.path.exists(os.path.join(tmp, "data", "alerts_state.json")), "the demo must not touch the push")
            r = subprocess.run([sys.executable, os.path.join(tmp, "scripts", "make_demo.py")], cwd=tmp, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "make_demo must not overwrite data/ without --force")


if __name__ == "__main__":
    unittest.main()
