#!/usr/bin/env python3
"""Gera data/carga.sql: o resultado do fluxo, as faturas e os limites, prontos pro Postgres (migration 0004).

Le data/fluxo.json, data/faturas.json e data/contas.json (que o atualizar.py ja gera) e escreve
INSERT ... ON CONFLICT DO UPDATE, entao rodar de novo nao duplica. So SQL padrao, sem dependencia:
  psql -h <servidor> -U ember -d ember -f data/carga.sql
Fica em data/ porque tem dado financeiro (fora do git).

Uso: python3 gerar_carga_sql.py
"""

import json
import math
import os
from datetime import date

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def ler(nome):
    caminho = os.path.join(RAIZ, "data", nome)
    return json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else []


def q(v):
    """Literal SQL: NULL, numero, booleano ou texto (E'' com aspas e barra escapadas,
    nao depende do standard_conforming_strings do Postgres). Descricao de Pix vem de
    quem manda o dinheiro, entao e texto externo e precisa de escape robusto.
    O certo seria query parametrizada, mas isso pede driver (psycopg) e o Ember e so stdlib com
    psql; entao o texto e escapado aqui, o byte NUL sai (o Postgres nao aceita NUL em text) e
    numero tem que ser finito (NaN e Infinity viram erro, nunca SQL)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            raise ValueError("numero nao finito na carga")
        return repr(v)
    texto = str(v).replace("\x00", "").replace("\\", "\\\\").replace("'", "''")
    return "E'" + texto + "'"


def upsert(tabela, colunas, chave, linhas):
    """chave: uma coluna ou varias separadas por virgula."""
    if not linhas:
        return []
    chaves = [c.strip() for c in chave.split(",")]
    atualizar = ", ".join(f"{c} = EXCLUDED.{c}" for c in colunas if c not in chaves)
    return [f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join(q(v) for v in l)}) "
            f"ON CONFLICT ({chave}) DO UPDATE SET {atualizar};" for l in linhas]


def main():
    fluxo, faturas, contas = ler("fluxo.json"), ler("faturas.json"), ler("contas.json")
    sql = [f"-- Ember, carga gerada em {date.today().isoformat()}: {len(fluxo)} linhas de fluxo, {len(faturas)} faturas.", "BEGIN;"]

    cols = ["id", "parte", "data", "data_caixa", "fonte", "conta", "descricao", "valor", "categoria", "essencialidade",
            "escopo", "motivo", "categoria_pluggy", "cartao", "tipo_fluxo"]
    vistas = {}
    for r in fluxo:  # mesma transacao em mais de uma linha vira parte 0, 1, ...
        r["_parte"] = vistas.get(r["id"], 0)
        vistas[r["id"]] = r["_parte"] + 1
    sql += upsert("mart.fluxo", cols, "id, parte", [
        [r["id"], r["_parte"], r["data"], r["data_caixa"], r["fonte"], r.get("conta"), r.get("descricao"), r["valor"], r.get("categoria"),
         r.get("essencialidade"), r.get("escopo"), r.get("motivo"), r.get("pluggy"), bool(r.get("cartao")), r["tipo_fluxo"]] for r in fluxo])

    cols = ["id", "fonte", "vencimento", "fechamento", "total", "pagamento_minimo", "permite_parcelar", "encargos"]
    sql += upsert("mart.fatura", cols, "id", [
        [b["id"], b["_fonte"], b["dueDate"][:10], (b.get("billClosingDate") or "")[:10] or None, b["totalAmount"],
         b.get("minimumPaymentAmount"), b.get("allowsInstallments"), round(sum(c["amount"] for c in b.get("financeCharges") or []), 2)]
        for b in faturas])

    cols = ["conta_id", "fonte", "nome", "limite", "disponivel", "pagamento_minimo", "vencimento", "lido_em"]
    sql += upsert("mart.cartao_limite", cols, "conta_id", [
        [c["id"], c["fonte"], c.get("nome"), c["credito"].get("creditLimit"), c["credito"].get("availableCreditLimit"),
         c["credito"].get("minimumPayment"), (c["credito"].get("balanceDueDate") or "")[:10] or None, c["atualizado"]]
        for c in contas if c.get("tipo") == "CREDIT" and c.get("credito")])

    sql.append("COMMIT;")
    caminho = os.path.join(RAIZ, "data", "carga.sql")
    open(caminho, "w", encoding="utf-8").write("\n".join(sql) + "\n")
    print(f"carga.sql: {len(sql) - 3} comandos ({len(fluxo)} fluxo, {len(faturas)} faturas)")


if __name__ == "__main__":
    os.umask(0o077)
    main()
