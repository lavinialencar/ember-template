#!/usr/bin/env python3
"""Consulta o CNAE de cada CNPJ que aparece na zona cinza e grava regras por documento.

Manda so o CNPJ de EMPRESA (dado publico) pra BrasilAPI. O resultado fica em
data/cnpj_cache.json e data/regras_cnpj.json (fora do git). O fluxo.py le as regras.
Rode depois de baixar_historico.py e fluxo.py; rode fluxo.py de novo no fim.
"""

import json
import os
import re
import time
import urllib.request

RAIZ = os.path.join(os.path.dirname(__file__), "..")
API = "https://brasilapi.com.br/api/cnpj/v1/"

# CNAE (2 ou 4 primeiros digitos) -> (categoria, essencialidade). O mais especifico ganha.
CNAE = {
    "5611": ("Alimentacao fora", "discricionario"), "5612": ("Alimentacao fora", "discricionario"),
    "5620": ("Alimentacao fora", "discricionario"), "56": ("Alimentacao fora", "discricionario"),
    "4711": ("Mercado", "variavel_essencial"), "4712": ("Mercado", "variavel_essencial"),
    "4721": ("Mercado", "variavel_essencial"), "4722": ("Mercado", "variavel_essencial"),
    "4723": ("Mercado", "variavel_essencial"), "4724": ("Mercado", "variavel_essencial"),
    "4729": ("Mercado", "variavel_essencial"),
    "4771": ("Farmacia", "variavel_essencial"), "4772": ("Cuidado pessoal", "discricionario"),
    "4781": ("Roupa e calcado", "discricionario"), "4782": ("Roupa e calcado", "discricionario"),
    "4783": ("Roupa e calcado", "discricionario"),
    "4751": ("Eletronicos e informatica", "discricionario"), "4752": ("Eletronicos e informatica", "discricionario"),
    "4753": ("Eletronicos e informatica", "discricionario"), "4754": ("Casa e mudanca", "variavel_essencial"),
    "4755": ("Casa e mudanca", "variavel_essencial"), "4756": ("Casa e mudanca", "variavel_essencial"),
    "4757": ("Casa e mudanca", "variavel_essencial"), "4759": ("Casa e mudanca", "variavel_essencial"),
    "4741": ("Moradia, manutencao", "variavel_essencial"), "4742": ("Moradia, manutencao", "variavel_essencial"),
    "4744": ("Moradia, manutencao", "variavel_essencial"), "4761": ("Livraria e papelaria", "discricionario"),
    "4762": ("Livraria e papelaria", "discricionario"), "4763": ("Lazer", "discricionario"),
    "47": ("Compras (marketplace)", "misto"),
    "86": ("Saude", "variavel_essencial"), "9602": ("Cuidado pessoal", "discricionario"),
    "93": ("Lazer", "discricionario"), "90": ("Lazer", "discricionario"), "5914": ("Lazer", "discricionario"),
    "55": ("Viagem", "discricionario"), "79": ("Viagem", "discricionario"),
    "4923": ("Transporte", "variavel_essencial"), "4921": ("Transporte", "variavel_essencial"),
    "85": ("Educacao", "discricionario"), "62": ("Software e servicos digitais", "discricionario"),
    "63": ("Software e servicos digitais", "discricionario"),
    "5091": ("Transporte", "variavel_essencial"), "5099": ("Transporte", "variavel_essencial"),
    "9529": ("Moradia, manutencao", "variavel_essencial"), "7420": ("Lazer", "discricionario"),
    "41": ("Moradia, manutencao", "variavel_essencial"), "43": ("Moradia, manutencao", "variavel_essencial"),
}


def so_digitos(v):
    return re.sub(r"\D", "", v or "")


def mapear(cnae):
    c = str(cnae)
    if not c.isascii() or not c.isdigit():  # cnae_fiscal vem da BrasilAPI: so digitos entram em regra
        return None
    for n in (4, 2):
        if c[:n] in CNAE:
            return CNAE[c[:n]]
    return None


def main():
    t = json.load(open(os.path.join(RAIZ, "data", "transacoes.json"), encoding="utf-8"))
    caminho_fluxo = os.path.join(RAIZ, "data", "fluxo.json")
    if not os.path.exists(caminho_fluxo):  # primeira rodada: o fluxo ainda nao existe, nao ha zona cinza pra consultar
        print("sem data/fluxo.json ainda, CNPJ fica pra proxima rodada")
        return
    fluxo = json.load(open(caminho_fluxo, encoding="utf-8"))
    por_id = {x["id"]: x for x in t}
    cnpjs = set()
    for r in fluxo:
        if r["tipo_fluxo"] != "gasto" or r["essencialidade"] != "cinza":
            continue
        x = por_id[r["id"]]
        d = (((x.get("paymentData") or {}).get("receiver") or {}).get("documentNumber") or {})
        c = so_digitos((x.get("merchant") or {}).get("cnpj")) or (so_digitos(d.get("value")) if d.get("type") == "CNPJ" else "")
        if len(c) == 14:
            cnpjs.add(c)

    cache_path = os.path.join(RAIZ, "data", "cnpj_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    pendentes = (cnpjs - set(cache)) | {c for c, v in cache.items() if "erro" in v}
    for c in sorted(pendentes):
        try:
            req = urllib.request.Request(API + c, headers={"User-Agent": "ember-pessoal/1.0 (consulta publica de CNPJ)", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.loads(resp.read())
            cache[c] = {k: d.get(k) for k in ("razao_social", "nome_fantasia", "cnae_fiscal", "cnae_fiscal_descricao", "municipio", "uf")}
        except Exception as e:  # noqa: BLE001
            cache[c] = {"erro": str(e)[:80]}
        time.sleep(0.4)
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    regras, sem = {}, []
    for c, d in cache.items():
        m = mapear(d.get("cnae_fiscal")) if d.get("cnae_fiscal") else None
        if m:
            regras[c] = {"categoria": m[0], "essencialidade": m[1], "cnae": d["cnae_fiscal"], "desc": d.get("cnae_fiscal_descricao"), "razao": d.get("razao_social")}
        else:
            sem.append((c, d.get("razao_social"), d.get("cnae_fiscal_descricao")))
    json.dump(regras, open(os.path.join(RAIZ, "data", "regras_cnpj.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(cnpjs)} CNPJs na zona cinza, {len(regras)} viraram regra, {len(sem)} sem mapa de CNAE")
    for c, rz, ds in sem[:15]:
        print("  sem mapa:", rz, "|", ds)


if __name__ == "__main__":
    os.umask(0o077)
    main()
