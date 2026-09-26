#!/usr/bin/env python3
"""Gera um data/ de DEMONSTRACAO, 100% inventado, pra ver o Ember rodando sem conta na Pluggy.

Escreve, no formato que a Pluggy devolve e que os scripts esperam:
  transacoes.json, faturas.json, contas.json, itens.json  (12 meses, dois bancos: banco_a e banco_b)
  regras_privadas.json, cadastro_manual.json               (copiados de exemplos/, com datas ajustadas pra hoje)
Comerciantes, pessoas e documentos sao ficticios ("Mercado Exemplo", "Padaria Modelo").

Uso: python3 scripts/gerar_exemplo.py [--destino PASTA] [--forcar]
     python3 scripts/atualizar.py --sem-api --sem-push --sem-backup   (depois: abre data/painel.html)
Recusa sobrescrever um data/ que ja tem transacoes.json (o seu dado de verdade), a nao ser com --forcar.
"""

import argparse
import json
import os
import random
from datetime import date, datetime, timedelta, timezone

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOJE = date.today()
TITULAR_DOC = "12345678900"  # igual ao exemplos/regras_privadas.exemplo.json; digito verificador errado de proposito
CARTOES = {"banco_a": {"fecha": 3, "vence": 10}, "banco_b": {"fecha": 20, "vence": 27}}


def mes_mais(d, n):
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def no_dia(mes, dia):
    return date(mes.year, mes.month, min(dia, 28))


class Gerador:
    def __init__(self, semente=42):
        self.rnd = random.Random(semente)
        self.trans = []
        self.n = 0

    def tx(self, fonte, tipo_conta, tipo, valor, d, descricao, categoria=None, hora=None, mcc=None, pagador=None, recebedor=None,
           parcela=None, moeda="BRL"):
        self.n += 1
        conta = f"conta-{fonte}-{'cartao' if tipo_conta == 'CREDIT' else 'corrente'}"
        quando = f"{d.isoformat()}T{hora or '03:00:00'}.000Z"
        # conta: saida negativa; cartao: compra positiva (convencao da Pluggy)
        sinal = (-1 if tipo == "DEBIT" else 1) * (-1 if tipo_conta == "CREDIT" else 1)
        t = {"id": f"tx-exemplo-{self.n:06d}", "accountId": conta, "date": quando, "description": descricao, "descriptionRaw": descricao,
             "amount": round(sinal * valor, 2), "type": tipo, "category": categoria, "status": "POSTED", "currencyCode": moeda,
             "_fonte": fonte, "_conta_nome": ("Cartao " if tipo_conta == "CREDIT" else "Conta ") + fonte.replace("_", " ").title(),
             "_conta_tipo": tipo_conta, "paymentData": None, "creditCardMetadata": None, "merchant": None}
        if pagador or recebedor:
            t["paymentData"] = {k: {"name": v[0], "documentNumber": {"type": "CPF" if len(v[1]) == 11 else "CNPJ", "value": v[1]}}
                                for k, v in (("payer", pagador), ("receiver", recebedor)) if v}
        if tipo_conta == "CREDIT" and tipo == "DEBIT":
            cfg = CARTOES[fonte]
            fechamento = no_dia(d, cfg["fecha"]) if d.day < cfg["fecha"] else no_dia(mes_mais(d, 1), cfg["fecha"])
            venc = no_dia(fechamento, cfg["vence"])
            t["creditCardMetadata"] = {"payeeMCC": mcc, "billForecastDate": venc.isoformat(), "installmentNumber": (parcela or (1, 1))[0],
                                       "totalInstallments": (parcela or (1, 1))[1], "_venc": venc.isoformat()}
        self.trans.append(t)
        return t

    def compras_do_mes(self, mes, ate):
        r = self.rnd
        loja = [  # (descricao, categoria Pluggy, MCC, vezes, min, max, cartao)
            ("MERCADO EXEMPLO", "Groceries", 5411, 7, 60, 320, "banco_a"),
            ("PADARIA MODELO", "Eating out", 5462, 8, 8, 40, "banco_a"),
            ("FARMACIA EXEMPLO", "Pharmacy", 5912, 2, 25, 120, "banco_a"),
            ("UBER *TRIP", "Taxi and ride-hailing", 4121, 6, 12, 45, "banco_a"),
            ("IFD*RESTAURANTE EXEMPLO", "Food delivery", 5812, 4, 35, 90, "banco_b"),
            ("LOJA DE ROUPAS MODELO", "Clothing", 5651, 1, 80, 260, "banco_b"),
            ("POSTO COMBUSTIVEL EXEMPLO", "Gas stations", 5541, 2, 90, 200, "banco_b"),
            ("LOJA SEM NOME 123", "Shopping", None, 2, 60, 220, "banco_b"),
            ("SERVICOS DIVERSOS XYZ", "Services", None, 1, 20, 60, "banco_a"),
        ]
        for desc, cat, mcc, vezes, vmin, vmax, fonte in loja:
            for _ in range(vezes):
                d = no_dia(mes, r.randint(1, 28))
                if d <= ate:
                    self.tx(fonte, "CREDIT", "DEBIT", round(r.uniform(vmin, vmax), 2), d, desc, cat, f"{r.randint(8, 21):02d}:{r.randint(0, 59):02d}:00", mcc)
        for desc, cat, mcc, dia, valor, fonte in (("STREAMING EXEMPLO", "Digital services", 4899, 12, 39.90, "banco_a"),
                                                   ("ACADEMIA EXEMPLO", "Gyms and fitness centers", 7997, 5, 119.90, "banco_b")):
            d = no_dia(mes, dia)
            if d <= ate:
                self.tx(fonte, "CREDIT", "DEBIT", valor, d, desc, cat, "10:00:00", mcc)
        if r.random() < 0.4 and no_dia(mes, 18) <= ate:
            self.tx("banco_b", "CREDIT", "DEBIT", round(r.uniform(28, 60), 2), no_dia(mes, 18), "CINEMA MODELO", "Entertainment", "19:30:00", 7832)
        if r.random() < 0.3 and no_dia(mes, 8) <= ate:
            self.tx("banco_a", "CREDIT", "DEBIT", round(r.uniform(90, 300), 2), no_dia(mes, 8), "GRAFICA MODELO", "Services", "14:10:00", 7338)


def gerar(destino):
    g = Gerador()
    r = g.rnd
    inicio = mes_mais(HOJE, -11)
    meses = [mes_mais(inicio, i) for i in range(12)]
    empresa = ("Empresa Exemplo Ltda", "00000000000191")
    titular = ("Fulana Exemplo", TITULAR_DOC)

    for i, mes in enumerate(meses):
        passou = lambda dia: no_dia(mes, dia) <= HOJE  # noqa: E731
        if passou(5):
            g.tx("banco_a", "BANK", "CREDIT", 6500.00, no_dia(mes, 5), "Salario EMPRESA EXEMPLO LTDA", "Salary", pagador=empresa)
        if passou(6):
            g.tx("banco_a", "BANK", "DEBIT", 800.00, no_dia(mes, 6), "PIX ENVIADO Fulana Exemplo", "Same person transfer", pagador=titular, recebedor=titular)
            g.tx("banco_b", "BANK", "CREDIT", 800.00, no_dia(mes, 6), "PIX RECEBIDO Fulana Exemplo", "Same person transfer", pagador=titular, recebedor=titular)
        if passou(10):
            g.tx("banco_a", "BANK", "DEBIT", 2400.00, no_dia(mes, 10), "PIX ENVIADO IMOBILIARIA EXEMPLO", "Transfer - PIX",
                 recebedor=("Imobiliaria Exemplo", "00000000000272"))
        if passou(15):
            g.tx("banco_a", "BANK", "DEBIT", round(r.uniform(170, 260), 2), no_dia(mes, 15), "Pagamento ENERGIA EXEMPLO SA", "Utilities")
        if passou(28):
            g.tx("banco_b", "BANK", "CREDIT", round(r.uniform(12, 20), 2), no_dia(mes, 28), "Rendimentos", "Proceeds interests and dividends")
        if i % 2 == 0 and passou(20):
            g.tx("banco_b", "BANK", "CREDIT", 1200.00, no_dia(mes, 20), "PIX RECEBIDO CLIENTE EXEMPLO", "Transfer - PIX", pagador=("Cliente Exemplo", "00000000000353"))
        if i in (3, 8) and passou(12):
            g.tx("banco_a", "BANK", "CREDIT", 150.00, no_dia(mes, 12), "PIX RECEBIDO SEGURADORA EXEMPLO", "Transfer - PIX", pagador=("Seguradora Exemplo", "00000000000434"))
        if i == 6 and passou(9):
            g.tx("banco_a", "BANK", "CREDIT", 3000.00, no_dia(mes, 9), "Credito consignado liberado", "Loans and financing")
        if i >= 6 and passou(11):
            g.tx("banco_a", "BANK", "DEBIT", 450.00, no_dia(mes, 11), "Parcela emprestimo BANCO EXEMPLO", "Loans and financing")
        if i in (7, 9) and passou(9):
            g.tx("banco_a", "BANK", "DEBIT", round(r.uniform(8, 25), 2), no_dia(mes, 9), "IOF", "Tax on financial operations")
        if i == 4 and passou(22):
            g.tx("banco_a", "BANK", "CREDIT", 50.00, no_dia(mes, 22), "PIX RECEBIDO Ciclano de Tal", "Transfer - PIX", pagador=("Ciclano de Tal", "00000000001"))
        g.compras_do_mes(mes, HOJE)

    # compra parcelada em 6x: parcelas passadas e futuras (as futuras viram compromisso_futuro)
    compra = no_dia(mes_mais(HOJE, -3), 14)
    for p in range(6):
        g.tx("banco_b", "CREDIT", "DEBIT", 250.00, no_dia(mes_mais(compra, p), 14), f"ELETRONICOS EXEMPLO PARC {p + 1:02d}/06",
             "Electronics", "16:40:00", 5732, parcela=(p + 1, 6))

    # recebivel: Pix de 300 do comprador nos dois ultimos meses (bate com o cadastro de exemplo)
    recebidas = []
    for n in (-2, -1):
        d = no_dia(mes_mais(HOJE, n), 21)
        g.tx("banco_b", "BANK", "CREDIT", 300.00, d, "PIX RECEBIDO COMPRADOR EXEMPLO", "Transfer - PIX", pagador=("Comprador Exemplo", "00000000002"))
        recebidas.append(d.strftime("%d/%m"))

    # compra internacional ontem: vira "compra estranha" nos alertas
    g.tx("banco_a", "CREDIT", "DEBIT", 89.00, HOJE - timedelta(days=1), "STORE EXAMPLE LTD USA", "Online shopping", "02:14:00", 5999, moeda="USD")

    # faturas: agrupa as compras por vencimento; so as que ja venceram existem na API
    por_fatura = {}
    for t in g.trans:
        m = t["creditCardMetadata"]
        if m and m["_venc"] <= HOJE.isoformat():
            por_fatura.setdefault((t["_fonte"], m["_venc"]), []).append(t)
    faturas = []
    for (fonte, venc), ts in sorted(por_fatura.items()):
        bid = f"fatura-{fonte}-{venc[:7]}"
        total = round(sum(abs(t["amount"]) for t in ts), 2)
        for t in ts:
            t["creditCardMetadata"]["billId"] = bid
        v = date.fromisoformat(venc)
        faturas.append({"id": bid, "dueDate": venc + "T00:00:00.000Z", "billClosingDate": no_dia(v, CARTOES[fonte]["fecha"]).isoformat() + "T00:00:00.000Z",
                        "totalAmount": total, "minimumPaymentAmount": round(total * 0.15, 2), "allowsInstallments": True,
                        "financeCharges": [], "_fonte": fonte, "_conta_nome": f"Cartao {fonte.replace('_', ' ').title()}"})
    # pagamento de cada fatura: a ultima do banco_b fica paga so em parte, pra demo do alerta de fatura vencida
    ultima_b = max((f for f in faturas if f["_fonte"] == "banco_b"), key=lambda f: f["dueDate"], default=None)
    for f in faturas:
        v = date.fromisoformat(f["dueDate"][:10])
        pago = round(f["totalAmount"] * (0.6 if f is ultima_b else 1), 2)
        g.tx(f["_fonte"], "BANK", "DEBIT", pago, v, "Pagamento de fatura", "Credit card payment")
        g.tx(f["_fonte"], "CREDIT", "CREDIT", pago, v, "Pagamento recebido", "Credit card payment")
    for t in g.trans:
        if t["creditCardMetadata"]:
            t["creditCardMetadata"].pop("_venc")

    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    contas = []
    for fonte, limite in (("banco_a", 6000), ("banco_b", 3000)):
        aberto = sum(abs(t["amount"]) for t in g.trans if t["_fonte"] == fonte and t["_conta_tipo"] == "CREDIT" and t["type"] == "DEBIT"
                     and not t["creditCardMetadata"].get("billId"))
        nome = fonte.replace("_", " ").title()
        contas.append({"fonte": fonte, "id": f"conta-{fonte}-corrente", "nome": f"Conta {nome}", "tipo": "BANK", "credito": None, "atualizado": HOJE.isoformat()})
        contas.append({"fonte": fonte, "id": f"conta-{fonte}-cartao", "nome": f"Cartao {nome}", "tipo": "CREDIT", "atualizado": HOJE.isoformat(),
                       "credito": {"creditLimit": limite, "availableCreditLimit": round(limite - aberto, 2), "minimumPayment": None, "balanceDueDate": None}})
    itens = {f: {"status": "UPDATED", "executionStatus": "SUCCESS", "lastUpdatedAt": agora} for f in CARTOES}

    exemplos = os.path.join(RAIZ, "exemplos")
    regras = json.load(open(os.path.join(exemplos, "regras_privadas.exemplo.json"), encoding="utf-8"))
    cad = json.load(open(os.path.join(exemplos, "cadastro_manual.exemplo.json"), encoding="utf-8"))
    cad["lido_em"] = (HOJE - timedelta(days=3)).isoformat()
    cad["recebiveis"][0]["recebidas"] = recebidas

    os.makedirs(destino, exist_ok=True)
    for nome, obj in (("transacoes.json", g.trans), ("faturas.json", faturas), ("contas.json", contas), ("itens.json", itens),
                      ("regras_privadas.json", regras), ("cadastro_manual.json", cad)):
        with open(os.path.join(destino, nome), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    print(f"exemplo: {len(g.trans)} transacoes, {len(faturas)} faturas, em {os.path.relpath(destino)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--destino", default=os.path.join(RAIZ, "data"))
    ap.add_argument("--forcar", action="store_true", help="sobrescreve um data/ que ja tem transacoes.json")
    a = ap.parse_args()
    if os.path.exists(os.path.join(a.destino, "transacoes.json")) and not a.forcar:
        raise SystemExit(f"{a.destino}/transacoes.json ja existe (pode ser o seu dado de verdade). Use --forcar pra sobrescrever.")
    gerar(a.destino)


if __name__ == "__main__":
    os.umask(0o077)
    main()
