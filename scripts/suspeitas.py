"""Detector de compra estranha no cartao. Usado por alertas.py; tambem roda sozinho pra teste retroativo.

So olha compras de cartao de credito (DEBIT em conta CREDIT). Compara cada compra recente com as compras anteriores
no proprio historico: nada de regra fixa por valor, o padrao e o do titular. Sinais:
  internacional  moeda diferente de BRL, ou pais no fim da descricao diferente de BR/BRA
  ramo novo      codigo de ramo (MCC) que nunca apareceu antes, em compra de R$ 50 ou mais
  rajada         3 ou mais comerciantes diferentes em ate 10 minutos
  novo e caro    comerciante que nunca apareceu, com valor acima do percentil 95 do historico e de R$ 300
Cidade nao entra: compra online costuma vir com a cidade da sede da loja, entao cidade gera alarme falso.
O botao "fui eu" (conhecidos) faz o ramo e o comerciante daquela compra deixarem de contar como novos.
"""

import os
import re
import statistics
import unicodedata
from datetime import datetime, timedelta

PAISES_OK = {"BR", "BRA"}


def hora_sem_hora():
    """Lancamento de banco sem hora vem como meia-noite local convertida pra UTC. Fuso em EMBER_TZ
    (padrao America/Sao_Paulo, onde isso da 03:00:00)."""
    try:
        from zoneinfo import ZoneInfo
        off = datetime.now(ZoneInfo(os.environ.get("EMBER_TZ") or "America/Sao_Paulo")).utcoffset()
        return (datetime(2000, 1, 2) - off).strftime("%H:%M:%S")
    except Exception:  # sem base de fusos no sistema: o Brasil inteiro sem horario de verao esta em UTC-3 ou perto
        return "03:00:00"


HORA_SEM_HORA = hora_sem_hora()


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def comerciante(desc):
    n = re.sub(r"\b(pix|compra|debito|credito|pagamento|de|da|do|em|parc|cp|mp|pg|pagto)\b", " ", re.sub(r"[^a-z ]", " ", norm(desc)))
    return " ".join(n.split()[:2])


def mcc(x):
    return (x.get("creditCardMetadata") or {}).get("payeeMCC")


def quando(x):
    return datetime.fromisoformat(x["date"].replace("Z", "+00:00")).replace(tzinfo=None)


def compras_cartao(trans):
    """Compra de verdade: cartao de credito, saida, com codigo de ramo (juros, IOF, multa e encargo nao tem) e nao e
    parcela seguinte de uma compra antiga."""
    out = []
    for x in trans:
        md = x.get("creditCardMetadata") or {}
        if x.get("_conta_tipo") == "CREDIT" and x["type"] == "DEBIT" and md.get("payeeMCC") and (md.get("installmentNumber") or 1) == 1:
            out.append(x)
    return out


def tem_hora(x):
    """Lancamento sem hora (meia-noite local em UTC): nele 'poucos minutos' nao quer dizer nada."""
    return quando(x).strftime("%H:%M:%S") != HORA_SEM_HORA


def analisar(trans, ini, fim, conhecidos_mcc=(), conhecidos_com=()):
    """Compras com data em [ini, fim] (datas) que fogem do padrao anterior a ini. Devolve lista de dicts."""
    compras = compras_cartao(trans)
    antes = [x for x in compras if quando(x).date() < ini]
    if len(antes) < 200:  # sem historico o "novo" nao quer dizer nada
        return []
    mccs = {mcc(x) for x in antes if mcc(x)} | set(conhecidos_mcc)
    coms = {comerciante(x["description"]) for x in antes} | set(conhecidos_com)
    valores = sorted(abs(x["amount"]) for x in antes)
    p95 = valores[int(len(valores) * 0.95)]
    janela = [x for x in compras if ini <= quando(x).date() <= fim]
    achados = []
    for x in janela:
        motivos = []
        desc = (x.get("descriptionRaw") or x["description"] or "").upper().strip()
        pais = re.search(r"\b([A-Z]{2,3})$", desc)
        if (x.get("currencyCode") or "BRL") != "BRL" or (pais and pais.group(1) not in PAISES_OK and len(pais.group(1)) == 3 and pais.group(1) not in ("LTD", "COM", "APP", "LTDA")):
            motivos.append("compra internacional")
        if mcc(x) and mcc(x) not in mccs and abs(x["amount"]) >= 50:  # ramo novo com centavos e quase sempre coisa legitima
            motivos.append("ramo de loja nunca visto")
        cm = comerciante(x["description"])
        if cm and cm not in coms and abs(x["amount"]) > max(300, p95):
            motivos.append("comerciante novo com valor alto")
        vizinhas = [y for y in janela if tem_hora(y) and tem_hora(x) and abs((quando(y) - quando(x)).total_seconds()) <= 600]
        if len({comerciante(y["description"]) for y in vizinhas}) >= 3:
            motivos.append("varias compras em poucos minutos")
        if motivos:
            achados.append({"id": x["id"], "data": x["date"], "comerciante": cm or desc[:30], "valor": abs(x["amount"]),
                            "cartao": x.get("_fonte"), "mcc": mcc(x), "motivos": motivos})
    return achados


if __name__ == "__main__":  # teste retroativo: quantos alertas teria dado nos ultimos 120 dias
    import json
    import os
    from collections import Counter
    RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    t = json.load(open(os.path.join(RAIZ, "data", "transacoes.json"), encoding="utf-8"))
    from datetime import date
    fim_total = date.today()  # o extrato tem parcelas futuras: nao usar a maior data
    vistos, por_motivo = {}, Counter()
    for d in range(120, -1, -1):
        dia = fim_total - timedelta(days=d)
        ate = [x for x in t if quando(x).date() <= dia]
        for a in analisar(ate, dia - timedelta(days=2), dia):
            if a["id"] not in vistos:
                vistos[a["id"]] = a
                for m in a["motivos"]:
                    por_motivo[m] += 1
    print(f"{len(vistos)} compras sinalizadas em 120 dias:", dict(por_motivo))
    for a in sorted(vistos.values(), key=lambda a: a["data"])[-25:]:
        print(a["data"][:16], a["cartao"], a["comerciante"][:28].ljust(28), round(a["valor"]), "|", "; ".join(a["motivos"]))
