#!/usr/bin/env python3
"""Motor de alertas do Ember: a regra fica aqui, separada de quem a executa.

Le data/ (faturas, cadastro manual, status das conexoes, transacoes) e grava data/alertas.json.
Roda dentro de atualizar.py (no computador ou no contêiner do servidor, pelo agendador.py).
Cada alerta tem uma chave estavel (pra nao duplicar tarefa no TickTick), um nivel
(vencido, atencao, info) e se exige acao sua (acao=True vira push e tarefa; o resto fica so no painel).

Alertas: fatura vencida, minimo vencendo, limite comprometido, assinatura sumida ou nova, melhor cartao,
recebivel atrasado, nota fiscal faltando, rotacao de cartao, compra estranha, fatura fechando,
divida vencendo, ponto vencendo, conexao parada, cadastro manual velho.
O que e cadastro (dividas, recebiveis, pontos, cartoes, assinaturas) vem de data/cadastro_manual.json.
"""

import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from config_privada import carregar_cadastro

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOJE = date.today()


def ler(nome, padrao):
    caminho = os.path.join(RAIZ, "data", nome)
    return json.load(open(caminho, encoding="utf-8")) if os.path.exists(caminho) else padrao


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def dmy(txt):
    """'30/09' ou '02/11/2026' -> a proxima data desse dia, no futuro ou hoje."""
    p = txt.split("/")
    d, m = int(p[0]), int(p[1])
    ano = int(p[2]) if len(p) > 2 else HOJE.year
    alvo = date(ano, m, d)
    if len(p) <= 2 and alvo < HOJE:
        alvo = date(ano + 1, m, d)
    return alvo


def slug(txt):
    return re.sub(r"[^a-z0-9]+", "_", norm(txt)).strip("_")[:40] or "item"


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    cad = carregar_cadastro()
    nomes = {c["fonte"]: c["nome"] for c in cad["cartoes"]}
    faturas = ler("faturas.json", [])
    itens = ler("itens.json", {})
    saida = []

    def add(chave, nivel, titulo, detalhe, prazo=None, acao=True, curto=None):
        saida.append({"chave": chave, "nivel": nivel, "titulo": titulo, "detalhe": detalhe, "curto": curto or detalhe, "prazo": prazo, "acao": acao})

    # 1. fatura vencida. A API de fatura NAO informa o que foi pago (payments vem vazio), entao o pagamento
    # e inferido dos creditos de "pagamento de fatura" no proprio cartao, atribuidos a fatura de vencimento
    # mais proxima. E estimativa: confirmar no app do banco.
    fluxo = ler("fluxo.json", [])
    pagamentos = [r for r in fluxo if r["tipo_fluxo"] == "neutro" and r.get("cartao") and ("fatura" in r["motivo"] or "quitacao" in r["motivo"])]
    por_fonte = defaultdict(list)
    for b in faturas:
        por_fonte[b["_fonte"]].append(b)
    pago = defaultdict(float)
    for r in pagamentos:
        dp = date.fromisoformat(r["data"])
        cand = [(abs((date.fromisoformat(b["dueDate"][:10]) - dp).days), b["id"]) for b in por_fonte[r["fonte"]]]
        cand = [c for c in cand if c[0] <= 20]
        if cand:
            pago[min(cand)[1]] += r["valor"]
    # Fatura com encargo financeiro (rotativo) ja carrega o saldo nao pago da anterior do mesmo cartao.
    # Sem isso o mesmo saldo entra duas vezes (a fatura seguinte ja soma o saldo da anterior).
    rolados = set()
    for b in faturas:
        if sum(c["amount"] for c in b.get("financeCharges") or []) > 0:
            v = date.fromisoformat(b["dueDate"][:10])
            for a in por_fonte[b["_fonte"]]:
                if 0 < (v - date.fromisoformat(a["dueDate"][:10])).days <= 45:
                    rolados.add(a["id"])
    abertas = []
    for b in faturas:
        venc = date.fromisoformat(b["dueDate"][:10])
        if b["id"] in rolados or venc >= HOJE or venc < HOJE - timedelta(days=60) or (b.get("totalAmount") or 0) <= 20:
            continue
        saldo = round(b["totalAmount"] - pago[b["id"]], 2)
        if saldo > max(20, 0.05 * b["totalAmount"]):
            nome = nomes.get(b["_fonte"], b["_fonte"])
            abertas.append((venc, nome, saldo, b["totalAmount"]))
    faturas_abertas = [{"cartao": a[1], "venc": a[0].isoformat(), "saldo": a[2], "total": a[3]} for a in sorted(abertas)]
    if abertas:
        abertas.sort()
        total = sum(a[2] for a in abertas)
        partes = "; ".join(f"{a[1]} {a[0].strftime('%m/%Y')}: {brl(a[2])} de {brl(a[3])}" for a in abertas)
        add("faturas-vencidas", "vencido", f"Faturas vencidas em aberto, {brl(total)} (estimado)",
            f"{partes}. Estimado pelos pagamentos identificados no extrato, confirme nos apps. Saldo de fatura vencida vai pro rotativo, com juros altos.", abertas[0][0].isoformat(),
            curto=", ".join(sorted({a[1] for a in abertas})) + ". Estimado pelo extrato, confirme nos apps.")

    # 1b. minimo do cartao vencendo em ate 3 dias. Fatura fechada vem da API (com o minimo); enquanto a fatura
    # ainda esta aberta a API nao a devolve, entao o vencimento e projetado pelo mesmo dia do mes da ultima fatura.
    for fonte, bs in por_fonte.items():
        if not bs:  # banco com pagamento no extrato mas sem fatura na API
            continue
        nome = nomes.get(fonte, fonte)
        venc_api = set()
        for b in bs:
            venc = date.fromisoformat(b["dueDate"][:10])
            venc_api.add(venc)
            dias = (venc - HOJE).days
            minimo = b.get("minimumPaymentAmount") or 0
            if 0 <= dias <= 3 and (b.get("totalAmount") or 0) > 20 and pago[b["id"]] < minimo:
                add(f"minimo-{fonte}-{venc.isoformat()}", "atencao", f"Cartão {nome} vence em {dias} dia(s)",
                    f"vence {venc.strftime('%d/%m')}, mínimo {brl(minimo)} de {brl(b['totalAmount'])}. Pagar o mínimo evita o atraso e a multa.",
                    venc.isoformat(), curto=f"{nome} vence dia {venc.strftime('%d/%m')}.")
        ultimo = max(date.fromisoformat(b["dueDate"][:10]) for b in bs)
        for mes_extra in (0, 1):
            m = HOJE.month + mes_extra
            ano, m = HOJE.year + (m - 1) // 12, (m - 1) % 12 + 1
            try:
                proj = date(ano, m, ultimo.day)
            except ValueError:
                continue
            if 0 <= (proj - HOJE).days <= 3 and proj not in venc_api:
                add(f"minimo-{fonte}-{proj.isoformat()}", "atencao", f"Cartão {nome} vence em {(proj - HOJE).days} dia(s)",
                    f"vence {proj.strftime('%d/%m')}; a fatura ainda não fechou na API, confira o valor e o mínimo no app.",
                    proj.isoformat(), curto=f"{nome} vence dia {proj.strftime('%d/%m')}.")

    # 1c. limite do cartao comprometido. Le o limite e o disponivel que a Pluggy informa (data/contas.json,
    # gravado por atualizar.py); nao estima nada. Avisa uma vez por mes por cartao.
    for c in ler("contas.json", []):
        cd = c.get("credito") or {}
        if c.get("tipo") != "CREDIT" or not cd.get("creditLimit"):
            continue
        usado = 1 - (cd.get("availableCreditLimit") or 0) / cd["creditLimit"]
        if usado >= 0.9:
            nome = nomes.get(c["fonte"], c["fonte"])
            add(f"limite-{c['fonte']}-{HOJE.strftime('%Y-%m')}", "atencao", f"Limite do {nome} comprometido",
                f"{usado * 100:.0f}% do limite em uso (disponível {brl(cd.get('availableCreditLimit') or 0)} de {brl(cd['creditLimit'])}). Sem folga pra compra nova, e acima de 100% pode gerar taxa.",
                curto=f"{nome} {usado * 100:.0f}% do limite.")

    # 1d. assinaturas. Conhecidas: cadastro_manual.assinaturas (nome, contem, mensal, so_valor). "Sumiu" = conhecida
    # mensal sem cobranca ha mais de 40 dias (pode ter falhado). "Nova" = cobranca que se repete todo mes, com valor
    # estavel, que nao esta na lista. Parcela e Pix nao contam. Voce decide o que entra na lista.
    conhecidas = [dict(a, chave=a["contem"]) for a in cad["assinaturas"]]
    trans = ler("transacoes.json", [])
    for k in conhecidas:
        if not k.get("mensal"):
            continue
        datas = sorted(x["date"][:10] for x in trans if x["type"] == "DEBIT" and k["chave"] in norm(x["description"] + " " + (x.get("descriptionRaw") or ""))
                       and (k.get("so_valor") is None or round(abs(x["amount"]), 2) == k["so_valor"]) and x["date"][:10] <= HOJE.isoformat())
        if len({d[:7] for d in datas}) >= 3 and (HOJE - date.fromisoformat(datas[-1])).days > 40:
            dias = (HOJE - date.fromisoformat(datas[-1])).days
            add(f"assinatura-sumiu-{slug(k['chave'])}-{datas[-1][:7]}", "atencao", f"Assinatura sem cobrança: {k['nome']}",
                f"última cobrança em {date.fromisoformat(datas[-1]).strftime('%d/%m')}, há {dias} dias. Pode ter falhado ou sido cancelada.",
                curto=f"{k['nome']}, há {dias} dias sem cobrança.")
    grupos = defaultdict(list)
    for x in trans:
        d = x["date"][:10]
        cat = (x.get("category") or "").lower()
        if x["type"] != "DEBIT" or x.get("status") == "PENDING" or d > HOJE.isoformat() or "transfer" in cat or "pix" in cat or "loan" in cat:
            continue
        if ((x.get("creditCardMetadata") or {}).get("totalInstallments") or 1) > 1:
            continue
        n = re.sub(r"\b(pix|enviado|recebido|compra|debito|credito|pagamento|de|da|do|em|parc|cp)\b", " ", re.sub(r"[^a-z ]", " ", norm(x["description"])))
        chave = " ".join(n.split()[:2])
        if chave:
            grupos[chave].append((d, abs(x["amount"])))
    novas = 0
    for chave, v in sorted(grupos.items()):
        meses = defaultdict(int)
        for d, _ in v:
            meses[d[:7]] += 1
        vals = sorted(a for _, a in v)
        med = vals[len(vals) // 2]
        estavel = sum(1 for a in vals if abs(a - med) <= 0.15 * med) / len(vals)
        recente = (HOJE - date.fromisoformat(max(d for d, _ in v))).days <= 45
        if len(meses) >= 3 and max(meses.values()) <= 1 and estavel >= 0.8 and recente and not any(k["chave"] in chave or chave in k["chave"] for k in conhecidas) and novas < 3:
            novas += 1
            add(f"assinatura-nova-{slug(chave)}", "atencao", f"Assinatura nova? {chave}",
                f"cobrança de uns {brl(med)} em {len(meses)} meses seguidos que não está na lista de assinaturas conhecidas. Se for assinatura, entra na lista; se não for, ignore.",
                curto="Cobrança mensal que não está no cadastro.")

    # 1e. melhor cartao pra comprar hoje: o que da mais dias ate pagar (dia de fechamento e de vencimento vem do
    # cadastro_manual.cartoes). Compra no dia do fechamento cai na fatura seguinte. So conta cartao com limite livre.
    livre = {c["fonte"]: (c.get("credito") or {}).get("availableCreditLimit") or 0 for c in ler("contas.json", [])}
    opcoes = []
    for c in cad["cartoes"]:
        if not c["fecha"] or not c["vence"]:
            continue
        fecha = date(HOJE.year, HOJE.month, c["fecha"]) if HOJE.day < c["fecha"] else date(HOJE.year + (HOJE.month // 12), HOJE.month % 12 + 1, c["fecha"])
        v_ano, v_mes = (fecha.year, fecha.month) if c["vence"] > fecha.day else (fecha.year + (fecha.month // 12), fecha.month % 12 + 1)
        opcoes.append(((date(v_ano, v_mes, c["vence"]) - HOJE).days, c["nome"], livre.get(c["fonte"], 0)))
    com_limite = [o for o in opcoes if o[2] > 50]
    if opcoes:
        if com_limite:
            d, n, lv = max(com_limite)
            add(f"melhor-cartao-{HOJE.isoformat()}", "info", f"Melhor cartão pra comprar hoje: {n}", f"{n}, {d} dias até pagar, com {brl(lv)} de limite livre.", acao=False)
        else:
            add(f"melhor-cartao-{HOJE.isoformat()}", "info", "Melhor cartão pra comprar hoje: nenhum", "Nenhum cartão cadastrado tem limite livre. Compra nova só em débito ou Pix.", acao=False)

    # 1f. recebivel atrasado (cadastro_manual.recebiveis: parcela, parcelas_total, recebidas "DD/MM"). Alerta a partir do
    # dia seguinte ao maior dia ja visto, se o mes atual ainda nao recebeu.
    for rb in cad["recebiveis"]:
        rec = [tuple(int(x) for x in r.split("/")[:2]) for r in rb["recebidas"]]
        if rec and len(rec) < rb["parcelas_total"] and not any(m == HOJE.month for _, m in rec) and HOJE.day > max(d for d, _ in rec):
            add(f"recebivel-{slug(rb['nome'])}-{HOJE.strftime('%Y-%m')}", "atencao", f"Recebível atrasado: {rb['nome']}",
                f"a parcela de {brl(rb['parcela'])} de {HOJE.strftime('%m/%Y')} ainda não caiu (costuma cair até o dia {max(d for d, _ in rec)}). {len(rec)} de {rb['parcelas_total']} recebidas.",
                curto="Parcela de recebível ainda não caiu.")

    # 1g. nota fiscal faltando, antes da declaracao do IR (a Receita costuma abrir em marco e fechar em 31/05).
    # Lista em cadastro_manual.notas_fiscais (prazo_ir e itens).
    nf = cad["notas_fiscais"] or {}
    if nf and date(HOJE.year, 1, 1) <= HOJE and date.fromisoformat(nf.get("prazo_ir", "2099-01-01")) - timedelta(days=120) <= HOJE <= date.fromisoformat(nf.get("prazo_ir", "2099-01-01")):
        faltam = [i for i in nf["itens"] if not i["tem_nota"] and not i["sobe_sozinho"]]
        if faltam:
            add(f"notas-faltando-{HOJE.strftime('%Y-%m')}", "atencao", f"{len(faltam)} nota(s) fiscal(is) faltando pro IR",
                f"prazo da declaração: {date.fromisoformat(nf['prazo_ir']).strftime('%d/%m/%Y')}. Faltam: " + ", ".join(i["descricao"] for i in faltam) + ".",
                nf["prazo_ir"], curto=f"{len(faltam)} despesas dedutíveis ainda sem nota.")

    # 1h. rotacao de cartao (trocar numero ou cartao virtual): 6 meses depois da ultima troca,
    # cadastro_manual.cartoes[].ultima_rotacao. Sem data, o alerta fica quieto.
    for c in cad["cartoes"]:
        ult = c.get("ultima_rotacao")
        if not ult:
            continue
        u = date.fromisoformat(ult)
        m = u.month + 6
        vence = date(u.year + (m - 1) // 12, (m - 1) % 12 + 1, min(u.day, 28))
        if HOJE >= vence:
            add(f"rotacao-{c['fonte']}-{ult}", "atencao", f"Rotação do cartão {c['nome']}",
                f"última rotação em {u.strftime('%d/%m/%Y')}, passaram 6 meses (venceu em {vence.strftime('%d/%m/%Y')}). Trocar o cartão e atualizar onde ele está cadastrado.",
                vence.isoformat(), curto=f"{c['nome']}, última troca em {u.strftime('%m/%Y')}.")

    # 1i. compra estranha no cartao (scripts/suspeitas.py). Olha os ultimos 3 dias; a Pluggy atualiza 1 vez por dia,
    # entao o aviso pode chegar ate 24h depois da compra (o bloqueio na hora e o app do banco). "Fui eu" (botao
    # Ignorar) ensina: o ramo e o comerciante daquela compra deixam de ser novos na proxima rodada.
    import suspeitas
    estado_alertas = ler("alertas_estado.json", {})
    conh_mcc, conh_com = set(), set()
    por_id = {x["id"]: x for x in trans}
    for ch in estado_alertas.get("ignorados", []):
        if ch.startswith("suspeita-") and ch[len("suspeita-"):] in por_id:
            x = por_id[ch[len("suspeita-"):]]
            conh_mcc.add(suspeitas.mcc(x))
            conh_com.add(suspeitas.comerciante(x["description"]))
    achados = suspeitas.analisar(trans, HOJE - timedelta(days=2), HOJE, conh_mcc, conh_com)
    for a in sorted(achados, key=lambda a: a["data"], reverse=True)[:5]:
        cartao = nomes.get(a["cartao"], a["cartao"])
        quando_txt = datetime.fromisoformat(a["data"].replace("Z", "+00:00")).strftime("%d/%m")
        add(f"suspeita-{a['id']}", "vencido", f"Compra estranha no cartão {cartao}: {a['comerciante']}",
            f"{quando_txt}, {brl(a['valor'])} em {a['comerciante']}. Motivo: {'; '.join(a['motivos'])}. Se não foi você, bloqueie o cartão no app e conteste a compra.",
            curto=f"{cartao}, {a['comerciante']} ({'; '.join(a['motivos'])}).")

    # 2. fatura fechando (o valor da fatura aberta so vem do app, entao usa o cadastro)
    for c in cad["cartoes"]:
        if not c["fecha"] or c["fatura_aberta"] is None:
            continue
        f = date(HOJE.year, HOJE.month, c["fecha"])
        if f < HOJE:
            f = date(HOJE.year + HOJE.month // 12, HOJE.month % 12 + 1, c["fecha"])
        if (f - HOJE).days <= 7:
            add(f"fatura-fechando-{c['fonte']}-{f.isoformat()}", "atencao", f"Fatura do {c['nome']} fechando",
                f"fecha em {f.strftime('%d/%m')}, {brl(c['fatura_aberta'])} até a última leitura do app", f.isoformat(), acao=False)

    # 3. divida vencendo em ate 10 dias (contrato ou informal, cadastro_manual.dividas[].proxima)
    for d in cad["dividas"]:
        if d["proxima"]:
            alvo = dmy(d["proxima"])
            if (alvo - HOJE).days <= 10:
                valor = d["parcela"] if d["parcela"] is not None else d["saldo"]
                titulo = ("Devolver: " if d["tipo"] == "informal" else "Parcela vencendo: ") + d["nome"]
                add(f"divida-{slug(d['nome'])}-{alvo.isoformat()}", "atencao", titulo, f"{brl(valor)} vence em {alvo.strftime('%d/%m')}", alvo.isoformat())

    # 4. ponto ou bonus vencendo em ate 60 dias
    for p in cad["pontos"]:
        if not p["expira"]:
            continue
        alvo = dmy(p["expira"])
        dias = (alvo - HOJE).days
        if 0 <= dias <= 60:
            quanto = brl(p["reais"]) if p["reais"] else f"{p['pts']:,.0f} pontos".replace(",", ".")
            add(f"pontos-{slug(p['programa'])}-{alvo.isoformat()}", "atencao" if dias <= 30 else "info", f"Pontos vencendo: {p['programa']}",
                f"{quanto} expiram em {alvo.strftime('%d/%m/%Y')}, faltam {dias} dias", alvo.isoformat())

    # 6. conexao parada
    for fonte, st in itens.items():
        ultima = st.get("lastUpdatedAt")
        velha = False
        if ultima:
            velha = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(ultima.replace("Z", "")[:19])).days >= 3
        if st.get("status") != "UPDATED" or st.get("executionStatus") not in ("SUCCESS", None) or velha:
            add(f"conexao-{fonte}", "vencido", f"Conexão parada: {fonte}", f"status {st.get('status')}, última atualização {str(ultima)[:10]}. Sem reconexão o extrato para de crescer em silêncio.")

    # 7. cadastro manual velho
    lido = cad["lido_em"]
    if lido and (HOJE - date.fromisoformat(lido)).days > 30:
        add("cadastro-velho", "info", "Cadastro manual desatualizado", f"lido em {date.fromisoformat(lido).strftime('%d/%m')}: fatura aberta, pontos, dívidas e recebíveis precisam de nova leitura dos apps", acao=False)

    ordem = {"vencido": 0, "atencao": 1, "info": 2}
    saida.sort(key=lambda a: (ordem[a["nivel"]], a["prazo"] or "9999"))
    with open(os.path.join(RAIZ, "data", "alertas.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado": HOJE.isoformat(), "itens": saida, "faturas_abertas": faturas_abertas}, f, ensure_ascii=False, indent=1)
    print(f"alertas: {len(saida)} ({sum(1 for a in saida if a['acao'])} com ação)")
    for a in saida:
        print(f"  [{a['nivel']}] {a['titulo']} | {a['detalhe'][:80]}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
