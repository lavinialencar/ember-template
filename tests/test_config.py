import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _base  # noqa: F401  (poe scripts/ no caminho)
import baixar_historico as b
import config_privada as cp
import fluxo

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EX = os.path.join(RAIZ, "exemplos")
A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"


def exemplo(nome):
    with open(os.path.join(EX, nome), encoding="utf-8") as f:
        return json.load(f)


class ItensPluggy(unittest.TestCase):
    def test_valido(self):
        self.assertEqual(b.itens_pluggy(f"banco_a:{A}, banco_b : {B.upper()} ,"), {"banco_a": A, "banco_b": B})

    def test_invalido(self):
        for ruim in (None, "", " , ", f"Banco:{A}", f"banco-a:{A}", f"{'x' * 31}:{A}", "banco_a:123", f"banco_a{A}",
                     f"banco_a:{A},banco_a:{B}", f"banco_a:{A}x", f"banco_a:../{A}", f"banco_a:{A}\nb:{B}"):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                b.itens_pluggy(ruim)

    def test_env_ganha_do_arquivo(self):
        antigo = os.environ.get("PLUGGY_ITEM_IDS")
        os.environ["PLUGGY_ITEM_IDS"] = f"banco_x:{A}"
        try:
            self.assertEqual(b.carregar_env()["PLUGGY_ITEM_IDS"], f"banco_x:{A}")
        finally:
            if antigo is None:
                del os.environ["PLUGGY_ITEM_IDS"]
            else:
                os.environ["PLUGGY_ITEM_IDS"] = antigo


class RegrasPrivadas(unittest.TestCase):
    def test_exemplo_valido_e_normalizado(self):
        r = cp.validar_regras(exemplo("regras_privadas.exemplo.json"))
        self.assertEqual(r["titular"]["documento"], "12345678900")
        self.assertTrue(all(p["escopo"] in ("pf", "pj") for p in r["padroes"]))
        obj = exemplo("regras_privadas.exemplo.json")
        obj["padroes"][0]["contem"] = "ACADEMIA  Exémplo"
        self.assertEqual(cp.validar_regras(obj)["padroes"][0]["contem"], "academia exemplo")

    def test_recusa(self):
        base = exemplo("regras_privadas.exemplo.json")
        estragos = [
            lambda o: o.update(chave_nova=1),
            lambda o: o["titular"].update(documento="123.456.789-00"),
            lambda o: o["titular"].update(nomes=["ana"]),
            lambda o: o["padroes"][0].update(essencialidade="luxo"),
            lambda o: o["padroes"][0].pop("essencialidade"),
            lambda o: o["padroes"][0].update(contem="ab"),
            lambda o: o["padroes"][0].update(contem="x" * 201),
            lambda o: o["padroes"][0].update(valor_min=10, valor_max=5),
            lambda o: o["padroes"][0].update(valor_min=float("nan")),
            lambda o: o["padroes"][0].update(escopo="empresa"),
            lambda o: o["entradas"][0].update(tipo="gasto"),
            lambda o: o["divisoes"][0]["partes"][0].update(proporcao=0.7),
            lambda o: o["divisoes"][0]["partes"].pop(),
            lambda o: o["assinaturas_grupos"][0].update(esporadica="sim"),
            lambda o: o.update(padroes={"contem": "x"}),
            lambda o: o.update(neutros=["x"] * (cp.LISTA_MAX + 1)),
        ]
        for i, estraga in enumerate(estragos):
            o = copy.deepcopy(base)
            estraga(o)
            with self.assertRaises(cp.ConfigInvalida, msg=f"estrago {i}"):
                cp.validar_regras(o)

    def test_cadastro_exemplo_e_recusa(self):
        base = exemplo("cadastro_manual.exemplo.json")
        c = cp.validar_cadastro(base)
        self.assertEqual(c["dividas"][2]["tipo"], "informal")
        for estraga in (lambda o: o["cartoes"][0].update(fonte="Banco A"), lambda o: o["cartoes"][0].update(fecha=31),
                        lambda o: o["dividas"][0].update(parcelas_pagas=99), lambda o: o["dividas"][1].pop("saldo"),
                        lambda o: o["recebiveis"][0].update(recebidas=["2026-06-21"]), lambda o: o.update(lido_em="ontem"),
                        lambda o: o["pontos"][0].update(pts=-1), lambda o: o.update(campo_velho={})):
            o = copy.deepcopy(base)
            estraga(o)
            with self.assertRaises(cp.ConfigInvalida):
                cp.validar_cadastro(o)


def tx(tipo, desc, pagador=None, recebedor=None, conta="BANK"):
    t = {"id": "t1", "date": "2020-01-10T03:00:00.000Z", "amount": -100.0 if tipo == "DEBIT" else 100.0, "type": tipo,
         "description": desc, "category": None, "_fonte": "banco_a", "_conta_nome": "Conta", "_conta_tipo": conta}
    if pagador or recebedor:
        t["paymentData"] = {k: {"name": v[0], "documentNumber": {"value": v[1]}} for k, v in (("payer", pagador), ("receiver", recebedor)) if v}
    return t


class Autotransferencia(unittest.TestCase):
    def ctx(self, **titular):
        regras = cp.validar_regras({"titular": titular})
        return {"regras": regras, "docs": {}, "caixa": lambda t: t["date"][:7], "aberta": {}, "regras_cnpj": {}}

    def classe(self, t, ctx):
        r = fluxo.classificar(t, ctx)[0]
        return r["tipo_fluxo"], r["motivo"]

    def test_por_documento(self):
        ctx = self.ctx(documento="12345678900", nomes=[])
        eu, outro = ("Qualquer Nome", "12345678900"), ("Outra Pessoa", "98765432101")
        self.assertEqual(self.classe(tx("DEBIT", "PIX ENVIADO", eu, eu), ctx)[0], "neutro")
        self.assertEqual(self.classe(tx("DEBIT", "PIX ENVIADO", None, eu), ctx)[0], "neutro")
        self.assertEqual(self.classe(tx("CREDIT", "PIX RECEBIDO", eu), ctx)[0], "neutro")
        self.assertNotEqual(self.classe(tx("DEBIT", "PIX ENVIADO", eu, outro), ctx)[0], "neutro")
        self.assertNotEqual(self.classe(tx("CREDIT", "PIX RECEBIDO", outro), ctx)[0], "neutro")

    def test_por_nome_quando_falta_documento(self):
        ctx = self.ctx(documento="", nomes=["Fulana Exemplo"])
        self.assertEqual(self.classe(tx("CREDIT", "PIX RECEBIDO FULANA EXEMPLO"), ctx)[0], "neutro")
        self.assertEqual(self.classe(tx("DEBIT", "Transferencia para Fulána Exemplo"), ctx)[0], "neutro")
        self.assertNotEqual(self.classe(tx("CREDIT", "PIX RECEBIDO BELTRANO"), ctx)[0], "neutro")

    def test_sem_config_nao_adivinha(self):
        ctx = self.ctx()
        self.assertEqual(self.classe(tx("CREDIT", "PIX RECEBIDO FULANA EXEMPLO", ("F", "12345678900")), ctx),
                         ("receita", "entrada sem regra"))

    def test_divisao_e_regra_pessoal(self):
        regras = cp.validar_regras(exemplo("regras_privadas.exemplo.json"))
        ctx = {"regras": regras, "docs": {}, "caixa": lambda t: t["date"][:7], "aberta": {}, "regras_cnpj": {}}
        linhas = fluxo.classificar(tx("DEBIT", "PIX ENVIADO IMOBILIARIA EXEMPLO"), ctx)
        self.assertEqual([(r["tipo_fluxo"], r["valor"]) for r in linhas], [("gasto", 50.0), ("neutro", 50.0)])
        r = fluxo.classificar(tx("DEBIT", "GRAFICA MODELO", conta="CREDIT"), ctx)[0]
        self.assertEqual((r["categoria"], r["escopo"]), ("Material de trabalho", "pj"))


class Demo(unittest.TestCase):
    def test_demo_ponta_a_ponta_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pasta in ("scripts", "exemplos"):
                shutil.copytree(os.path.join(RAIZ, pasta), os.path.join(tmp, pasta), ignore=shutil.ignore_patterns("__pycache__"))
            env = {k: v for k, v in os.environ.items() if not k.startswith(("PLUGGY_", "NTFY_", "ALERTA_", "BACKUP_"))}
            for cmd in (["gerar_exemplo.py"], ["atualizar.py", "--sem-api", "--sem-push", "--sem-backup"]):
                r = subprocess.run([sys.executable, os.path.join(tmp, "scripts", cmd[0]), *cmd[1:]], cwd=tmp, env=env,
                                   capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            painel = os.path.join(tmp, "data", "painel.html")
            self.assertTrue(os.path.exists(painel))
            html = open(painel, encoding="utf-8").read()
            self.assertNotIn("__DADOS__", html)
            self.assertNotIn("__CSP_SCRIPT_HASH__", html)
            self.assertIn("Mercado", html)
            self.assertFalse(os.path.exists(os.path.join(tmp, "data", "alertas_estado.json")), "demo nao pode mexer no push")
            r = subprocess.run([sys.executable, os.path.join(tmp, "scripts", "gerar_exemplo.py")], cwd=tmp, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, "gerar_exemplo nao pode sobrescrever data/ sem --forcar")


if __name__ == "__main__":
    unittest.main()
