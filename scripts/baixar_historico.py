#!/usr/bin/env python3
"""Baixa o historico completo (12 meses) de cada banco conectado e grava em data/transacoes.json.

data/ fica fora do git (dado financeiro). Rode de novo quando quiser atualizar.
A apiKey vale 2h, o script autentica do zero toda vez.
Quais conexoes baixar vem de PLUGGY_ITEM_IDS no .env (ou no ambiente): "fonte:itemId,fonte:itemId".
"""

import json
import math
import os
import re
import urllib.request

API_BASE = "https://api.pluggy.ai"
RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FONTE_OK = re.compile(r"^[a-z0-9_]{1,30}$")
UUID_OK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def carregar_env():
    """Le o .env (se existir); variavel de ambiente com o mesmo nome ganha (util no contêiner e no CI)."""
    valores = {}
    caminho = os.path.join(RAIZ, ".env")
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    chave, valor = linha.split("=", 1)
                    valores[chave.strip()] = valor.strip().strip('"')
    for chave in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS"):
        if os.environ.get(chave):
            valores[chave] = os.environ[chave]
    return valores


def itens_pluggy(texto):
    """'banco_a:<uuid>,banco_b:<uuid>' -> {'banco_a': '<uuid>', ...}. fonte e o rotulo que aparece no painel e nas
    regras ([a-z0-9_], ate 30); itemId e o UUID da conexao na Pluggy (MeuPluggy). Qualquer coisa fora disso para tudo."""
    itens = {}
    for par in (texto or "").split(","):
        par = par.strip()
        if not par:
            continue
        fonte, sep, item_id = par.partition(":")
        fonte, item_id = fonte.strip(), item_id.strip().lower()
        if not sep or not FONTE_OK.fullmatch(fonte):
            raise ValueError(f"PLUGGY_ITEM_IDS: rotulo invalido em '{fonte[:40]}' (use a-z, 0-9 e _, ate 30)")
        if not UUID_OK.fullmatch(item_id):
            raise ValueError(f"PLUGGY_ITEM_IDS: itemId de '{fonte}' nao e um UUID")
        if fonte in itens:
            raise ValueError(f"PLUGGY_ITEM_IDS: rotulo '{fonte}' repetido")
        itens[fonte] = item_id
    if not itens:
        raise ValueError("PLUGGY_ITEM_IDS vazio: defina no .env, ex. banco_a:<itemId>,banco_b:<itemId>")
    return itens


def chamar(url, api_key=None, metodo="GET", corpo=None):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key
    dados = json.dumps(corpo).encode() if corpo else None
    req = urllib.request.Request(url, data=dados, headers=headers, method=metodo)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


PROXIMO_OK = re.compile(r"^\?[A-Za-z0-9=&_%.-]+$")


def proxima_pagina(proximo):
    """URL da proxima pagina de /v2/transactions, ou None. "next" da Pluggy e so uma query string;
    qualquer outra coisa (outro host, caminho, caractere estranho) encerra a paginacao com aviso."""
    if not proximo:
        return None
    if not isinstance(proximo, str) or not PROXIMO_OK.fullmatch(proximo):
        print("aviso: 'next' da Pluggy fora do formato esperado; paginacao encerrada nesta conta")
        return None
    return f"{API_BASE}/v2/transactions{proximo}"


def transacao_ok(t):
    """Checagem minima do que vem da API: id e data texto, valor numero finito."""
    return (isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("date"), str)
            and isinstance(t.get("amount"), (int, float)) and not isinstance(t.get("amount"), bool)
            and math.isfinite(t["amount"]))


def so_validas(res):
    boas = [t for t in res if transacao_ok(t)]
    if len(boas) != len(res):
        print(f"aviso: {len(res) - len(boas)} transacoes malformadas ignoradas")
    return boas


def main():
    env = carregar_env()
    itens = itens_pluggy(env.get("PLUGGY_ITEM_IDS"))  # valida antes de gastar chamada na API
    api_key = chamar(
        f"{API_BASE}/auth",
        metodo="POST",
        corpo={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]},
    )["apiKey"]

    todas = []
    for fonte, item_id in itens.items():
        contas = chamar(f"{API_BASE}/accounts?itemId={item_id}", api_key=api_key)
        for conta in contas.get("results", []):
            url = f"{API_BASE}/v2/transactions?accountId={conta['id']}"
            while url:
                pagina = chamar(url, api_key=api_key)
                for t in so_validas(pagina.get("results", [])):
                    t["_fonte"] = fonte
                    t["_conta_nome"] = conta.get("name")
                    t["_conta_tipo"] = conta.get("type")
                    todas.append(t)
                # "next" e a query string inteira da proxima pagina, nao um token
                url = proxima_pagina(pagina.get("next"))
        print(f"{fonte}: ok")

    destino = os.path.join(RAIZ, "data", "transacoes.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(todas, f, ensure_ascii=False)
    print(f"{len(todas)} transacoes gravadas em {destino}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
