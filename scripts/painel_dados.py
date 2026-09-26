#!/usr/bin/env python3
"""Agrega data/fluxo.json e data/faturas.json em data/painel.json, a base do painel do Ember.

Fora do git (data/). O que e cadastro manual (dividas, recebiveis, pontos, cartoes, assinaturas) vem de
data/cadastro_manual.json; os grupos de assinatura do grafico vem de data/regras_privadas.json.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import date

from config_privada import carregar_cadastro, carregar_regras, norm

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.umask(0o077)  # data/painel.json so pro dono
fluxo = json.load(open(os.path.join(RAIZ, "data", "fluxo.json"), encoding="utf-8"))
faturas = json.load(open(os.path.join(RAIZ, "data", "faturas.json"), encoding="utf-8"))
t = json.load(open(os.path.join(RAIZ, "data", "transacoes.json"), encoding="utf-8"))
CAD = carregar_cadastro()
REGRAS = carregar_regras()
_ALERTAS = os.path.join(RAIZ, "data", "alertas.json")
ALERTAS = json.load(open(_ALERTAS, encoding="utf-8")) if os.path.exists(_ALERTAS) else {"itens": [], "faturas_abertas": []}

HOJE = date.today()
CUR = HOJE.strftime("%Y-%m")


def mes_mais(ym, n):
    k = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{k // 12}-{k % 12 + 1:02d}"


# janela movel: os 12 meses ate o atual. Cartoes so aparecem bem depois do primeiro mes de dado,
# entao os 3 primeiros meses da historia sao "incompletos"; o atual e parcial; o resto e fechado.
MESES = [mes_mais(CUR, -k) for k in range(11, -1, -1)]
_PRIMEIRO = min(x["date"][:7] for x in t)
INCOMPLETO = {m for m in MESES if m <= mes_mais(_PRIMEIRO, 2)}
PARCIAL = {CUR}
FECHADOS = [m for m in MESES if m not in INCOMPLETO and m not in PARCIAL]
NF = max(len(FECHADOS), 1)


def r0(x):
    return int(round(x))


mes = {m: defaultdict(float) for m in MESES}
for r in fluxo:
    m = r["data_caixa"]
    if m not in mes:
        continue
    v, tf = r["valor"], r["tipo_fluxo"]
    if r.get("escopo", "pf") != "pf":  # escopo pj (empresa, projeto) pago ou recebido no pessoal: fica fora, so em nota
        if tf == "gasto":
            mes[m]["projeto"] += v
        elif tf in ("receita", "receita_unica"):
            mes[m]["projeto_rec"] += v
        continue
    if tf == "receita":
        mes[m]["decimo" if (r["categoria"] or "").startswith("13o") else ("salario" if r["categoria"] == "Salario" else "outras")] += v
    elif tf == "receita_unica":
        mes[m]["unica"] += v
    elif tf == "reembolso":
        mes[m]["reembolso"] += v
    elif tf == "divida_entrando":
        mes[m]["divida_entra"] += v
    elif tf == "gasto":
        mes[m]["gasto_" + (r["essencialidade"] or "cinza")] += v
        cat = r["categoria"] or ""
        if cat.startswith(("Juros", "Tarifa", "IOF", "Custo da divida")):
            mes[m]["custo_divida"] += v
        if cat.startswith("Equipamento"):
            mes[m]["equip"] += v
    elif tf == "estorno":
        mes[m]["estorno"] += v

linhas_mes = []
for m in MESES:
    d = mes[m]
    gasto = d["gasto_fixo_compromissado"] + d["gasto_variavel_essencial"] + d["gasto_discricionario"] + d["gasto_misto"] + d["gasto_cinza"] - d["estorno"]
    linhas_mes.append({
        "mes": m, "incompleto": m in INCOMPLETO, "parcial": m in PARCIAL,
        "salario": r0(d["salario"]), "decimo": r0(d["decimo"]), "unica": r0(d["unica"]), "reembolso": r0(d["reembolso"]),
        "outras": r0(d["outras"]), "divida_entra": r0(d["divida_entra"]), "gasto": r0(gasto),
        "fixo": r0(d["gasto_fixo_compromissado"]), "essencial": r0(d["gasto_variavel_essencial"]),
        "discric": r0(d["gasto_discricionario"]), "misto": r0(d["gasto_misto"]), "cinza": r0(d["gasto_cinza"]), "estorno": r0(d["estorno"]),
        "custo_divida": r0(d["custo_divida"]), "equip": r0(d["equip"]), "projeto": r0(d["projeto"]), "projeto_rec": r0(d["projeto_rec"]),
    })


def media(campo, meses=FECHADOS):
    return sum(x[campo] for x in linhas_mes if x["mes"] in meses) / NF


ACENTO = {"Roupa e calcado": "Roupa e calçado", "Casa e mudanca": "Casa e mudança", "Alimentacao": "Alimentação", "Saude": "Saúde",
          "Farmacia": "Farmácia", "Familia": "Família", "Custo da divida": "Custo da dívida", "Tarifa bancaria": "Tarifa bancária",
          "Emprestimo": "Empréstimo", "Eletronicos": "Eletrônicos", "Educacao": "Educação"}


def grupo(c):
    """Junta as subcategorias na mesma familia: 'Moradia, energia' e 'Moradia, aluguel' viram 'Moradia'."""
    g = (c or "").split(",")[0].strip()
    if g == "Moradia":
        sub = (c.split(",")[1].strip().lower() if "," in c else "")
        return "Aluguel" if sub.startswith("aluguel") else "Energia" if sub.startswith("energia") else "Manutenção da casa"
    for chave, nome in ACENTO.items():
        if g.startswith(chave):
            return nome
    return g


# categorias (meses fechados), so as classificadas, e cinza por tipo Pluggy
cat = Counter()
cinza_pluggy = Counter()
cinza_n = Counter()
motivos = defaultdict(lambda: [0, 0.0])
for r in fluxo:
    if r["tipo_fluxo"] != "gasto" or r["data_caixa"] not in FECHADOS or r.get("escopo", "pf") != "pf":
        continue
    if r["essencialidade"] == "cinza":
        cinza_pluggy[r["pluggy"] or "Sem tipo"] += r["valor"]
        cinza_n[r["pluggy"] or "Sem tipo"] += 1
        k = "sem regra segura"
    else:
        if not (r["categoria"] or "").startswith("Equipamento"):
            cat[grupo(r["categoria"])] += r["valor"]
        k = "regra"
    motivos[k][0] += 1
    motivos[k][1] += r["valor"]

# faturas por cartao: um cartao por rotulo de fonte que tem fatura; nome e limite vem do cadastro
CARTAO_CAD = {c["fonte"]: c for c in CAD["cartoes"]}
ultimo = {}
for f in faturas:
    ultimo[f["_fonte"]] = max(ultimo.get(f["_fonte"], ""), f["dueDate"][:7])

cartoes = []
futuro_mes = defaultdict(float)
for fonte in sorted(ultimo):
    cc = CARTAO_CAD.get(fonte, {})
    aberta = mes_mais(ultimo[fonte], 1)
    fech = sorted([f for f in faturas if f["_fonte"] == fonte], key=lambda f: f["dueDate"])[-4:]
    est = sum(r["valor"] for r in fluxo if r["fonte"] == fonte and r["cartao"] and r["tipo_fluxo"] == "gasto" and r["data_caixa"] == aberta)
    est -= sum(r["valor"] for r in fluxo if r["fonte"] == fonte and r["cartao"] and r["tipo_fluxo"] == "estorno" and r["data_caixa"] == aberta)
    do_app = cc.get("fatura_aberta") is not None
    cartoes.append({
        "nome": cc.get("nome", fonte), "limite": cc.get("limite"),
        "fechadas": [{"venc": f["dueDate"][:10], "total": r0(max(f["totalAmount"], 0))} for f in fech],
        "aberta_mes": aberta, "aberta_estimada": r0(cc["fatura_aberta"] if do_app else est), "aberta_do_app": do_app,
    })
for r in fluxo:
    if r["tipo_fluxo"] == "compromisso_futuro" and r["cartao"]:
        futuro_mes[r["data_caixa"]] += r["valor"]
ABERTA = cartoes[0]["aberta_mes"] if cartoes else mes_mais(CUR, 1)


# assinaturas: grupos do grafico em regras_privadas.assinaturas_grupos; itens (o que cobra hoje) no cadastro
def linhas_de(chave, so_valor=None, excluir_valor=None):
    out = []
    for x in t:
        if x["type"] != "DEBIT":
            continue
        n = norm(x.get("description", "") + " " + (x.get("descriptionRaw") or ""))
        v = round(abs(x["amount"]), 2)
        if chave in n and (so_valor is None or v == so_valor) and (excluir_valor is None or v != excluir_valor):
            out.append((x["date"][:10], v))
    return sorted(out)


GRUPOS = list(dict.fromkeys(g["grupo"] for g in REGRAS["assinaturas_grupos"]))
assin_mes = {m: defaultdict(float) for m in MESES}
esporadicas = defaultdict(float)
for g in REGRAS["assinaturas_grupos"]:
    for d, v in linhas_de(g["contem"], g["so_valor"], g["excluir_valor"]):
        if d[:7] in assin_mes:
            assin_mes[d[:7]][g["grupo"]] += v
            if g["esporadica"]:
                esporadicas[g["grupo"]] += v
assin = {
    "grupos": GRUPOS,
    "meses": [{"mes": m, **{g: round(assin_mes[m][g], 2) for g in GRUPOS}} for m in MESES],
    "itens": [{"nome": a["nome"], "valor": a["valor"] or 0, "detalhe": a["detalhe"]} for a in CAD["assinaturas"] if a["mensal"]],
    "esporadicas": [{"nome": g, "total12": round(v, 2)} for g, v in esporadicas.items()],
}

# Moradia: o valor de um mes normal (mediana), porque a media dilui quando falta mes
_al = [r for r in fluxo if r["tipo_fluxo"] == "gasto" and (r["categoria"] or "") == "Moradia, aluguel"]
_en = [r for r in fluxo if r["tipo_fluxo"] == "gasto" and (r["categoria"] or "") == "Moradia, energia"]
moradia = {
    "aluguel": {"tipico": r0(sorted(r["valor"] for r in _al)[len(_al) // 2]) if _al else 0, "meses": len({r["data_caixa"] for r in _al})},
    "energia": {"media": r0(sum(r["valor"] for r in _en) / len(_en)) if _en else 0, "min": r0(min((r["valor"] for r in _en), default=0)),
                "max": r0(max((r["valor"] for r in _en), default=0)), "meses": len({r["data_caixa"] for r in _en})},
}


def divida(d):
    pago = round(d["parcelas_pagas"] * d["parcela"], 2) if d["parcela"] is not None else None
    if d["saldo"] is not None:
        a_pagar = d["saldo"]
    else:
        a_pagar = round((d["parcelas_total"] - d["parcelas_pagas"]) * d["parcela"], 2)
    return {**d, "a_pagar": a_pagar, "pago": pago}


rend = sum(r["valor"] for r in fluxo if r["categoria"] == "Rendimento" and r["data_caixa"] in FECHADOS)
saida = {
    "faturas_abertas": ALERTAS.get("faturas_abertas", []),
    "alertas": ALERTAS.get("itens", []),
    "gerado": HOJE.isoformat(), "meses": linhas_mes, "fechados": FECHADOS, "lido_em": CAD["lido_em"],
    "ref": {"atual": CUR, "anterior": mes_mais(CUR, -1), "anterior2": mes_mais(CUR, -2), "aberta": ABERTA},
    "media": {k: r0(media(k)) for k in ("salario", "gasto", "fixo", "essencial", "discric", "misto", "cinza", "custo_divida", "divida_entra", "estorno")},
    "categorias": [{"nome": k, "valor": r0(v / NF)} for k, v in cat.most_common(10)],
    "rendimento": {"total": r0(rend), "media": r0(rend / NF)},
    "moradia": moradia,
    "projeto": {"custo": sum(x["projeto"] for x in linhas_mes if x["mes"] in FECHADOS), "receita": sum(x["projeto_rec"] for x in linhas_mes if x["mes"] in FECHADOS)},
    "avulsos": [{"nome": "Equipamento (compras únicas)", "valor": r0(sum(r["valor"] for r in fluxo if r["tipo_fluxo"] == "gasto" and (r["categoria"] or "").startswith("Equipamento")))}],
    "cinza_pluggy": [{"tipo": k, "valor": r0(v / NF), "linhas": cinza_n[k]} for k, v in cinza_pluggy.most_common(10)],
    "cobertura": {"regra_linhas": motivos["regra"][0], "regra_valor": r0(motivos["regra"][1]),
                  "cinza_linhas": motivos["sem regra segura"][0], "cinza_valor": r0(motivos["sem regra segura"][1])},
    "cartoes": cartoes, "futuro_cartao": [{"mes": k, "valor": r0(v)} for k, v in sorted(futuro_mes.items())],
    "assinaturas": assin,
    "pontos": CAD["pontos"],
    "recebiveis": CAD["recebiveis"],
    "dividas": [divida(d) for d in CAD["dividas"]],
    "n_regras": len(REGRAS["padroes"]) + len(REGRAS["entradas"]) + len(REGRAS["divisoes"]),
    "dividas_entrando_12m": r0(sum(x["divida_entra"] for x in linhas_mes)),
    "custo_divida_12m": r0(sum(x["custo_divida"] for x in linhas_mes)),
    "custo_divida_aberta": r0(sum(r["valor"] for r in fluxo if r["tipo_fluxo"] == "gasto" and r["data_caixa"] == ABERTA
                                  and (r["categoria"] or "").startswith(("Juros", "Tarifa", "IOF", "Custo da divida")))),
}
with open(os.path.join(RAIZ, "data", "painel.json"), "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=1)
print(json.dumps({k: saida[k] for k in ("media", "cobertura", "dividas_entrando_12m", "custo_divida_12m")}, ensure_ascii=False))
print(json.dumps(saida["categorias"], ensure_ascii=False))
for x in linhas_mes:
    print(x["mes"], x["salario"], x["decimo"], x["unica"], x["reembolso"], x["outras"], "|", x["gasto"], x["fixo"], x["essencial"], x["discric"], x["cinza"], x["estorno"], "| div", x["divida_entra"], x["custo_divida"])
