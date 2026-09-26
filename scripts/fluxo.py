#!/usr/bin/env python3
"""Tabela normalizada de fluxo do Ember: tipo_fluxo e data_caixa de cada transacao.

Le data/transacoes.json e data/faturas.json (rode baixar_historico.py e baixar_faturas.py
antes), aplica as regras e grava data/fluxo.json. Tudo em data/ fica fora do git.

tipo_fluxo: gasto, receita, receita_unica, reembolso, divida_entrando, neutro,
            estorno, compromisso_futuro.
data_caixa: mes (AAAA-MM) em que o dinheiro se move de verdade. Cartao: vencimento da
            fatura (billId), nunca a data da compra. Conta: a propria data.

Ordem das regras: as suas (data/regras_privadas.json, validadas por config_privada.py) vem antes
das genericas deste arquivo; o que nenhuma regra segura pega cai na zona cinza, pra voce decidir.
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import date

from config_privada import carregar_regras, norm

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOJE = date.today().isoformat()


def desc(t):
    return t.get("descriptionRaw") or t.get("description") or ""


def doc_lado(t, lado):
    return (((t.get("paymentData") or {}).get(lado) or {}).get("documentNumber") or {}).get("value")


def nome_lado(t, lado):
    return ((t.get("paymentData") or {}).get(lado) or {}).get("name")


# Categoria da Pluggy -> (categoria, essencialidade), so as confiaveis (sql/0003)
MAPA_PLUGGY = {
    "Hospital clinics and labs": ("Saude", "variavel_essencial"),
    "Clothing": ("Roupa e calcado", "discricionario"),
    "Groceries": ("Mercado", "variavel_essencial"),
    "Pharmacy": ("Farmacia", "variavel_essencial"),
    "Healthcare": ("Saude", "variavel_essencial"),
    "Dentist": ("Saude", "variavel_essencial"),
    "Insurance": ("Seguro", "fixo_compromissado"),
    "Eating out": ("Alimentacao fora", "discricionario"),
    "Food delivery": ("Alimentacao, delivery", "discricionario"),
    "Interests charged": ("Juros", "fixo_compromissado"),
    "Late payment and overdraft costs": ("Juros e multa", "fixo_compromissado"),
    "Bank fees": ("Tarifa bancaria", "fixo_compromissado"),
    "Tax on financial operations": ("IOF", "fixo_compromissado"),
}
CUSTO_DIVIDA = {"Interests charged", "Late payment and overdraft costs", "Bank fees", "Tax on financial operations"}

# Codigo de ramo do cartao (MCC), que ja vem em toda compra no cartao. So vale quando nenhuma regra sua pegou antes.
MCC_MAP = {}
for _cod, _cat, _ess in [
    ((5811, 5812, 5813, 5814, 5462), "Alimentacao fora", "discricionario"),
    ((5411, 5422, 5441, 5451, 5499), "Mercado", "variavel_essencial"),
    ((5912, 5122), "Farmacia", "variavel_essencial"),
    ((8011, 8021, 8031, 8041, 8042, 8043, 8049, 8050, 8062, 8071, 8099), "Saude", "variavel_essencial"),
    ((4121, 4111, 4112, 4131, 4789), "Transporte", "variavel_essencial"),
    ((5541, 5542, 5983), "Transporte, combustivel", "variavel_essencial"),
    ((5611, 5621, 5631, 5641, 5651, 5661, 5681, 5691, 5699, 5137), "Roupa e calcado", "discricionario"),
    ((5712, 5713, 5714, 5718, 5719, 5722), "Casa e mudanca", "variavel_essencial"),
    ((5200, 5211, 5231, 5251, 5261, 5072), "Moradia, manutencao", "variavel_essencial"),
    ((7832, 7841, 7922, 7929, 7932, 7933, 7941, 7991, 7992, 7993, 7994, 7996, 7997, 7998, 7999), "Lazer", "discricionario"),
    ((7230, 7297, 7298, 5977), "Cuidado pessoal", "discricionario"),
    ((5940, 5941), "Lazer", "discricionario"),
    ((5942, 5943, 5945, 5947), "Livraria e papelaria", "discricionario"),
    ((5732, 5734, 5045, 5044, 5946), "Eletronicos e informatica", "discricionario"),
    ((7371, 7372, 7379, 4816), "Software e servicos digitais", "discricionario"),
    ((8211, 8220, 8241, 8244, 8249, 8299), "Educacao", "discricionario"),
    ((7011, 7012, 4511, 4722, 4723), "Viagem", "discricionario"),
    ((4814, 4899), "Telecom e celular", "variavel_essencial"),
    ((4900,), "Utilidades", "variavel_essencial"),
]:
    for _c in _cod:
        MCC_MAP[_c] = (_cat, _ess)

# Padroes de descricao genericos, alta confianca. Os seus (lojas, contrapartes) vao em data/regras_privadas.json.
PADROES = [
    # marketplace mistura casa, pessoal e trabalho na mesma compra: fica "misto" de proposito
    ("mercadolivre", ("Compras (marketplace)", "misto")),
    ("aliexpress", ("Compras (marketplace)", "misto")),
    ("amazon marketplace", ("Compras (marketplace)", "misto")),
    ("amazonmktplc", ("Compras (marketplace)", "misto")),
    ("amazon br", ("Compras (marketplace)", "misto")),
    ("uber trip", ("Transporte", "variavel_essencial")),
    ("ifd ", ("Alimentacao, delivery", "discricionario")),
    ("ifood", ("Alimentacao, delivery", "discricionario")),
]

PALAVRAS_EMPRESTIMO = ("credito consignado", "pix no credito", "credito em parcelas", "liberacao de dinheiro", "aprovacao do credito")
PALAVRAS_ESTORNO = ("reembolso", "estorno", "devolucao", "cancelado", "transferencia enviada")
PALAVRAS_PAGAMENTO_CARTAO = ("pagamento", "fatura", "debito compulsorio", "credito de atraso", "encerramento de divida")


def carregar_regras_cnpj():
    """Regras por CNPJ (CNAE consultado por scripts/enriquecer_cnpj.py), fora do git."""
    caminho = os.path.join(RAIZ, "data", "regras_cnpj.json")
    return json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else {}


def na_faixa(r, valor):
    return (r["valor_min"] is None or valor >= r["valor_min"]) and (r["valor_max"] is None or valor <= r["valor_max"])


def texto_contraparte(t):
    return norm(desc(t)) + " | " + norm(nome_lado(t, "receiver" if t["type"] == "DEBIT" else "payer"))


def resolver_documentos(d, regras):
    """Mapa documento -> trecho da regra (padroes), achado pelo nome na descricao ou no recebedor.
    Depois disso a regra vale pelo documento, mesmo se a descricao mudar."""
    docs = {}
    for t in d:
        n = texto_contraparte(t)
        for r in regras["padroes"]:
            if r["contem"] in n:
                doc = doc_lado(t, "receiver") if t["type"] == "DEBIT" else doc_lado(t, "payer")
                if doc:
                    docs[doc] = r["contem"]
    return docs


def eh_titular(t, n, regras, lado):
    """Movimento entre contas do proprio titular: documento igual ao do titular, ou um dos nomes dele na descricao."""
    doc = regras["titular"]["documento"]
    if doc and doc_lado(t, lado) == doc:
        return True
    return any(nome in n for nome in regras["titular"]["nomes"])


def deslocamento_por_banco(faturas, d):
    """Meses entre billForecastDate e o vencimento da fatura, por banco (moda)."""
    por_id = {b["id"]: b for b in faturas}
    c = defaultdict(Counter)
    for t in d:
        m = t.get("creditCardMetadata") or {}
        b = por_id.get(m.get("billId"))
        if t["type"] == "DEBIT" and b and m.get("billForecastDate"):
            a, v = m["billForecastDate"], b["dueDate"][:7]
            c[t["_fonte"]][(int(v[:4]) - int(a[:4])) * 12 + int(v[5:7]) - int(a[5:7])] += 1
    return {f: cnt.most_common(1)[0][0] for f, cnt in c.items()}


def somar_meses(ym, n):
    a, m = int(ym[:4]), int(ym[5:7])
    k = a * 12 + (m - 1) + n
    return f"{k // 12}-{k % 12 + 1:02d}"


def classificar(t, ctx):
    """Devolve lista de linhas (uma, ou mais se a transacao for dividida)."""
    regras = ctx["regras"]
    n = norm(desc(t))
    data = (t.get("date") or "")[:10]
    valor = abs(t["amount"])
    cartao = t["_conta_tipo"] == "CREDIT"
    credito = t["type"] == "CREDIT"
    base = {
        "id": t["id"], "data": data, "fonte": t["_fonte"], "conta": t.get("_conta_nome"),
        "descricao": desc(t)[:80], "valor": valor, "categoria": None, "essencialidade": None,
        "escopo": "pf", "motivo": "", "pluggy": t.get("category"), "cartao": cartao,
    }

    def linha(tipo, cat=None, ess=None, motivo="", data_caixa=None, v=None, escopo=None):
        r = dict(base, tipo_fluxo=tipo, categoria=cat, essencialidade=ess, motivo=motivo)
        if escopo:
            r["escopo"] = escopo
        r["data_caixa"] = data_caixa or (ctx["caixa"](t) if cartao else data[:7])
        if v is not None:
            r["valor"] = v
        return [r]

    for tx in regras["neutros"]:
        if tx in n:
            return linha("neutro", motivo="regra neutra sua (regras_privadas.neutros)")

    if cartao and not credito and "saldo em atraso" in n:
        return linha("neutro", motivo="saldo em atraso rolado, anulado pelo credito de atraso")

    # 1. cartao ---------------------------------------------------------------
    if cartao and not credito and ctx["caixa"](t) > ctx["aberta"].get(t["_fonte"], "9999-99"):
        return linha("compromisso_futuro", motivo="parcela de fatura que ainda nao abriu")
    if cartao and credito:
        if any(k in n for k in PALAVRAS_PAGAMENTO_CARTAO):
            return linha("neutro", motivo="pagamento de fatura ou quitacao de saldo em atraso")
        return linha("estorno", motivo="credito no cartao")

    # 2. entrada na conta -----------------------------------------------------
    if credito:
        cp = texto_contraparte(t)
        for r in regras["entradas"]:
            if r["contem"] in cp and na_faixa(r, valor):
                return linha(r["tipo"], r["categoria"], motivo="regra de entrada sua", escopo=r["escopo"])
        if t.get("category") == "Salary" or "salario" in n:
            return linha("receita", "Salario", motivo="salario (categoria da Pluggy ou descricao)")
        if "receita federal" in n:
            return linha("receita_unica", "Restituicao de IR", motivo="lote da Receita Federal")
        if t.get("category") == "Loans and financing" or any(k in n for k in PALAVRAS_EMPRESTIMO):
            return linha("divida_entrando", "Emprestimo", motivo="divida entrando, nao e receita")
        if eh_titular(t, n, regras, "payer") or "cofrinho" in n:
            return linha("neutro", motivo="movimento entre contas do titular")
        if any(k in n for k in PALAVRAS_ESTORNO):
            return linha("estorno", motivo="reembolso ou estorno de um pagamento")
        if n.startswith("rendimento") or t.get("category") == "Proceeds interests and dividends":
            return linha("receita_unica", "Rendimento", motivo="rendimento de conta")
        if "cashback" in n:
            return linha("receita_unica", "Cashback")
        return linha("receita", "Receita a classificar", "cinza", motivo="entrada sem regra")

    # 3. saida da conta e compra no cartao -------------------------------------
    if data > HOJE:
        return linha("compromisso_futuro", motivo="parcela futura")
    if not cartao:
        if "fatura" in n or n.startswith("pagamento cartao de credito") or "pagamento com saldo" in n:
            return linha("neutro", motivo="pagamento de fatura")
        if "quitacao antecipada" in n:
            return linha("neutro", motivo="quitacao antecipada de divida, amortizacao e nao gasto")
        doc = regras["titular"]["documento"]
        if doc and doc_lado(t, "receiver") == doc and doc_lado(t, "payer") in (doc, None):
            return linha("neutro", motivo="autotransferencia")
        if eh_titular(t, n, regras, "receiver") or "cofrinho" in n:
            return linha("neutro", motivo="movimento entre contas do titular")

    cp = texto_contraparte(t)
    for dv in regras["divisoes"]:
        if dv["contem"] in cp and na_faixa(dv, valor):
            out = []
            for p in dv["partes"]:
                out += linha(p["tipo"], p["categoria"], p["essencialidade"], motivo="divisao sua", v=round(valor * p["proporcao"], 2), escopo=p["escopo"])
            return out

    por_doc = ctx["docs"].get(doc_lado(t, "receiver"))
    for r in regras["padroes"]:
        if (r["contem"] == por_doc or r["contem"] in cp) and na_faixa(r, valor):
            return linha(r["tipo"], r["categoria"], r["essencialidade"], motivo="regra sua (regras_privadas.padroes)", escopo=r["escopo"])

    for trecho, (cat, ess) in PADROES:
        if trecho in n:
            return linha("gasto", cat, ess, motivo="padrao de descricao")

    rec = re.sub(r"\D", "", doc_lado(t, "receiver") or "")
    cn = re.sub(r"\D", "", (t.get("merchant") or {}).get("cnpj") or "") or (rec if len(rec) == 14 else "")
    if cn in ctx["regras_cnpj"]:
        rc = ctx["regras_cnpj"][cn]
        return linha("gasto", rc["categoria"], rc["essencialidade"], motivo="CNAE " + str(rc["cnae"]) + ", " + str(rc["desc"]))
    mcc = (t.get("creditCardMetadata") or {}).get("payeeMCC")
    if mcc in MCC_MAP:
        cat, ess = MCC_MAP[mcc]
        return linha("gasto", cat, ess, motivo="MCC " + str(mcc))

    pc = t.get("category")
    if pc in MAPA_PLUGGY:
        cat, ess = MAPA_PLUGGY[pc]
        return linha("gasto", cat, ess, motivo="categoria Pluggy" + (", custo da divida" if pc in CUSTO_DIVIDA else ""))
    return linha("gasto", "A classificar", "cinza", motivo="sem regra segura, zona cinza")


def main():
    regras = carregar_regras()
    d = json.load(open(os.path.join(RAIZ, "data", "transacoes.json"), encoding="utf-8"))
    faturas = json.load(open(os.path.join(RAIZ, "data", "faturas.json"), encoding="utf-8"))
    por_id = {b["id"]: b for b in faturas}
    desloc = deslocamento_por_banco(faturas, d)
    docs = resolver_documentos(d, regras)

    with open(os.path.join(RAIZ, "data", "regras_contraparte.json"), "w", encoding="utf-8") as f:
        json.dump({"documento_para_regra": docs}, f, ensure_ascii=False, indent=1)

    def caixa(t):
        m = t.get("creditCardMetadata") or {}
        b = por_id.get(m.get("billId"))
        if b:
            return b["dueDate"][:7]
        if m.get("billForecastDate"):
            return somar_meses(m["billForecastDate"], desloc.get(t["_fonte"], 0))
        return (t.get("date") or "")[:7]

    # a API nao devolve a fatura aberta: a aberta e o mes seguinte ao ultimo vencimento de cada banco.
    # Caixa depois da aberta e compromisso futuro (parcela que ainda nao abriu), nao gasto realizado.
    ultimo = {}
    for f in faturas:
        ultimo[f["_fonte"]] = max(ultimo.get(f["_fonte"], ""), f["dueDate"][:7])
    aberta = {fonte: somar_meses(m, 1) for fonte, m in ultimo.items()}
    ctx = {"docs": docs, "caixa": caixa, "aberta": aberta, "regras": regras, "regras_cnpj": carregar_regras_cnpj()}
    fluxo = []
    for t in d:
        fluxo.extend(classificar(t, ctx))

    # cauda longa: contraparte cinza com menos de R$ 300 nos 12 meses vira "Diversos (miudos)", misto.
    # So o que pesa (R$ 300 ou mais) continua na zona cinza pra voce decidir.
    por_id = {x["id"]: x for x in d}

    def chave_cp(r):
        x = por_id[r["id"]]
        doc = doc_lado(x, "receiver") if x["type"] == "DEBIT" else doc_lado(x, "payer")
        if doc and x["_conta_tipo"] == "BANK":
            return doc
        n = re.sub(r"[0-9*/]+", " ", norm(desc(x)))
        return re.sub(r"\s+", " ", n).strip()[:24]

    soma = defaultdict(float)
    for r in fluxo:
        if r["tipo_fluxo"] == "gasto" and r["essencialidade"] == "cinza" and r["escopo"] == "pf":
            soma[chave_cp(r)] += r["valor"]
    for r in fluxo:
        if r["tipo_fluxo"] == "gasto" and r["essencialidade"] == "cinza" and r["escopo"] == "pf" and soma[chave_cp(r)] < 300:
            r["categoria"], r["essencialidade"], r["motivo"] = "Diversos (miudos)", "misto", "contraparte pequena sem regra, menos de R$ 300"
    with open(os.path.join(RAIZ, "data", "fluxo.json"), "w", encoding="utf-8") as f:
        json.dump(fluxo, f, ensure_ascii=False)

    print(f"{len(fluxo)} linhas de fluxo a partir de {len(d)} transacoes. Deslocamento fatura por banco: {desloc}")
    print("Por tipo_fluxo:", dict(Counter(r["tipo_fluxo"] for r in fluxo)))

    mes = defaultdict(Counter)
    for r in fluxo:
        m = r["data_caixa"]
        if r["tipo_fluxo"] in ("receita", "receita_unica", "reembolso", "divida_entrando"):
            mes[m][r["tipo_fluxo"]] += r["valor"]
        elif r["tipo_fluxo"] == "gasto":
            mes[m]["gasto"] += r["valor"]
            mes[m]["cinza"] += r["valor"] if r["essencialidade"] == "cinza" else 0
            mes[m]["n_cinza"] += 1 if r["essencialidade"] == "cinza" else 0
        elif r["tipo_fluxo"] == "estorno":
            mes[m]["gasto"] -= r["valor"]
        elif r["tipo_fluxo"] == "compromisso_futuro":
            mes[m]["futuro"] += r["valor"]

    limite = max(aberta.values(), default=HOJE[:7])
    print("\nMES CAIXA   receita  unica  reembolso  divida_entra    gasto  (cinza R$, n)   futuro")
    for m in [k for k in sorted(mes) if k <= limite][-13:]:
        c = mes[m]
        print(
            f"{m}   {c['receita']:>7,.0f} {c['receita_unica']:>6,.0f} {c['reembolso']:>9,.0f} {c['divida_entrando']:>12,.0f}"
            f" {c['gasto']:>8,.0f}   ({c['cinza']:>6,.0f}, {c['n_cinza']:>3})  {c['futuro']:>7,.0f}"
        )


if __name__ == "__main__":
    os.umask(0o077)
    main()
