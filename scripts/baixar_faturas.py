#!/usr/bin/env python3
"""Baixa as faturas (GET /bills) dos cartoes e grava em data/faturas.json.

Serve pro mes de caixa do cartao: a data de vencimento da fatura diz quando o dinheiro
sai, nao a data da compra. data/ fica fora do git. Autentica do zero (apiKey vale 2h).
"""

import json
import os

from baixar_historico import API_BASE, RAIZ, carregar_env, chamar, itens_pluggy


def main():
    env = carregar_env()
    itens = itens_pluggy(env.get("PLUGGY_ITEM_IDS"))  # valida antes de gastar chamada na API
    api_key = chamar(
        f"{API_BASE}/auth",
        metodo="POST",
        corpo={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]},
    )["apiKey"]

    faturas = []
    for fonte, item_id in itens.items():
        contas = chamar(f"{API_BASE}/accounts?itemId={item_id}", api_key=api_key)
        for conta in contas.get("results", []):
            if conta.get("type") != "CREDIT":
                continue
            pagina = chamar(f"{API_BASE}/bills?accountId={conta['id']}&pageSize=500", api_key=api_key)
            for b in pagina.get("results", []):
                b["_fonte"] = fonte
                b["_conta_nome"] = conta.get("name")
                faturas.append(b)
            print(f"{fonte} {conta.get('name')}: {len(pagina.get('results', []))} faturas")

    with open(os.path.join(RAIZ, "data", "faturas.json"), "w", encoding="utf-8") as f:
        json.dump(faturas, f, ensure_ascii=False, indent=1)
    print(f"{len(faturas)} faturas gravadas em data/faturas.json")


if __name__ == "__main__":
    os.umask(0o077)
    main()
