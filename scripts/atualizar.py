#!/usr/bin/env python3
"""Atualiza tudo do Ember de uma vez, sem gastar o limite da API da Pluggy.

Passos: baixa so o que e novo (janela recente e parcelas futuras) e o status das conexoes e junta na base local,
baixa as faturas, consulta CNPJ novo, roda o fluxo e os alertas, manda o push (ntfy), gera data/painel.html
e faz o backup criptografado (BACKUP_DESTINO).
A API devolve do mais novo pro mais velho; por isso a janela e trocada inteira (o id de
uma transacao pode mudar quando deixa de ser PENDING), sem duplicar.

Uso: python3 atualizar.py                (roda tudo)
     python3 atualizar.py --sem-api      (so refaz fluxo e painel com o que ja tem em data/)
     python3 atualizar.py --sem-push     (nao manda push nem le respostas do ntfy)
     python3 atualizar.py --sem-backup   (nao grava backup)
Demo, tudo offline: python3 scripts/gerar_exemplo.py && python3 scripts/atualizar.py --sem-api --sem-push --sem-backup
Saida: data/painel.html (fora do git; tem dado financeiro).
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta

from baixar_historico import API_BASE, RAIZ, carregar_env, chamar, itens_pluggy, proxima_pagina, so_validas

JANELA_DIAS = 25  # o que a Pluggy ainda pode alterar (PENDING vira POSTED)
AQUI = os.path.dirname(os.path.abspath(__file__))


def baixar_novo():
    caminho = os.path.join(RAIZ, "data", "transacoes.json")
    base = json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else []
    shutil.copy(caminho, caminho.replace(".json", ".antes.json")) if os.path.exists(caminho) else None
    corte = (date.today() - timedelta(days=JANELA_DIAS)).isoformat()
    env = carregar_env()
    itens = itens_pluggy(env.get("PLUGGY_ITEM_IDS"))
    chave = chamar(f"{API_BASE}/auth", metodo="POST", corpo={"clientId": env["PLUGGY_CLIENT_ID"], "clientSecret": env["PLUGGY_CLIENT_SECRET"]})["apiKey"]
    chamadas, novas = 0, 0
    status = {}
    todas_contas = []
    for fonte, item_id in itens.items():
        it = chamar(f"{API_BASE}/items/{item_id}", api_key=chave)
        chamadas += 1
        status[fonte] = {k: it.get(k) for k in ("status", "executionStatus", "lastUpdatedAt")}
        contas = chamar(f"{API_BASE}/accounts?itemId={item_id}", api_key=chave)
        chamadas += 1
        for conta in contas.get("results", []):
            conta_id = conta["id"]
            todas_contas.append({"fonte": fonte, "id": conta_id, "nome": conta.get("name"), "tipo": conta.get("type"),
                                 "credito": conta.get("creditData") or None, "atualizado": date.today().isoformat()})
            ja_tem = any(x["accountId"] == conta_id for x in base)
            recebidas, url, incompleta = [], f"{API_BASE}/v2/transactions?accountId={conta_id}", False
            while url:
                pagina = chamar(url, api_key=chave)
                chamadas += 1
                res = so_validas(pagina.get("results", []))
                for x in res:
                    x["_fonte"], x["_conta_nome"], x["_conta_tipo"] = fonte, conta.get("name"), conta.get("type")
                recebidas.extend(res)
                # ordem: do mais novo pro mais velho. Conta que ja existe: para quando a pagina inteira
                # e mais velha que a janela (as parcelas futuras vem primeiro e sao percorridas).
                if ja_tem and res and max((x.get("date") or "")[:10] for x in res) < corte:
                    break
                url = proxima_pagina(pagina.get("next"))
                incompleta = bool(pagina.get("next")) and url is None
            if ja_tem and incompleta:  # paginacao cortada: trocar a janela apagaria o que nao veio; fica a base antiga
                print("aviso: conta com paginacao incompleta, janela mantida como estava")
            elif ja_tem:
                base = [x for x in base if not (x["accountId"] == conta_id and ((x.get("date") or "")[:10] >= corte))]
                novas_conta = [x for x in recebidas if (x.get("date") or "")[:10] >= corte]
                base.extend(novas_conta)
                novas += len(novas_conta)
            else:
                base.extend(recebidas)
                novas += len(recebidas)
    with open(os.path.join(RAIZ, "data", "contas.json"), "w", encoding="utf-8") as f:
        json.dump(todas_contas, f, ensure_ascii=False, indent=1)
    with open(os.path.join(RAIZ, "data", "itens.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False)
    print(f"API: {chamadas} chamadas, base com {len(base)} transacoes")


def rodar(script, *args):
    r = subprocess.run([sys.executable, os.path.join(AQUI, script), *args], capture_output=True, text=True)
    print(f"{script}: {'ok' if r.returncode == 0 else 'ERRO'}")
    if r.returncode != 0:
        print(r.stderr[-800:])
        raise SystemExit(1)


def rodar_opcional(script, *args):
    """Passo que nao pode derrubar o resto (ex.: push sem internet)."""
    r = subprocess.run([sys.executable, os.path.join(AQUI, script), *args], capture_output=True, text=True)
    print(f"{script}: {'ok' if r.returncode == 0 else 'falhou, segue sem ele'}")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr[-400:])


def main():
    os.umask(0o077)  # tudo que o Ember cria em data/ (e os scripts filhos, que herdam) fica so pro dono
    desconhecidas = [a for a in sys.argv[1:] if a not in ("--sem-api", "--sem-push", "--sem-backup")]
    if desconhecidas:
        raise SystemExit("opcao desconhecida: " + " ".join(desconhecidas))
    if "--sem-api" not in sys.argv:
        baixar_novo()
        rodar("baixar_faturas.py")
        rodar("enriquecer_cnpj.py")
    rodar("fluxo.py")
    rodar("alertas.py")
    if "--sem-push" not in sys.argv:
        rodar_opcional("notificar.py")
    rodar("painel_dados.py")
    rodar("painel_montar.py")
    if "--sem-backup" not in sys.argv:
        rodar("backup.py")
    print("pronto: data/painel.html")


if __name__ == "__main__":
    main()
