"""Carrega e valida os dois arquivos pessoais do Ember, que moram em data/ (fora do git):

  data/regras_privadas.json   regras de classificacao que dependem de quem voce e (nome, documento,
                              contrapartes, divisoes). Usado por fluxo.py e painel_dados.py.
  data/cadastro_manual.json   o que a API nao traz: dividas, recebiveis, pontos, cartoes, assinaturas.
                              Usado por alertas.py e painel_dados.py.

Modelos com dado inventado em exemplos/. Arquivo invalido para tudo com uma mensagem clara: e melhor
nao gerar painel do que gerar um painel errado em silencio.
"""

import json
import math
import os
import re
import unicodedata

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

TIPOS_FLUXO = ("gasto", "receita", "receita_unica", "reembolso", "divida_entrando", "neutro", "estorno", "compromisso_futuro")
ESSENCIALIDADES = ("fixo_compromissado", "variavel_essencial", "discricionario", "misto", "cinza")
ESCOPOS = ("pf", "pj")
TEXTO_MAX = 200
LISTA_MAX = 2000
FONTE_OK = re.compile(r"^[a-z0-9_]{1,30}$")
DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIA_MES = re.compile(r"^\d{2}/\d{2}(/\d{4})?$")


def norm(s):
    """Minusculo, sem acento, espacos colapsados: a forma em que toda descricao e comparada."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


class ConfigInvalida(ValueError):
    pass


def _erro(onde, msg):
    raise ConfigInvalida(f"{onde}: {msg}")


def _texto(v, onde, minimo=1, opcional=False):
    if v is None and opcional:
        return None
    if not isinstance(v, str) or not (minimo <= len(v) <= TEXTO_MAX):
        _erro(onde, f"texto de {minimo} a {TEXTO_MAX} caracteres")
    return v


def _numero(v, onde, opcional=True, minimo=None):
    if v is None and opcional:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        _erro(onde, "numero finito")
    if minimo is not None and v < minimo:
        _erro(onde, f"numero maior ou igual a {minimo}")
    return v


def _inteiro(v, onde, minimo=0, maximo=None, opcional=True):
    if v is None and opcional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimo or (maximo is not None and v > maximo):
        _erro(onde, f"inteiro entre {minimo} e {maximo if maximo is not None else 'infinito'}")
    return v


def _enum(v, opcoes, onde, padrao=None):
    if v is None:
        return padrao
    if v not in opcoes:
        _erro(onde, "um de " + ", ".join(opcoes))
    return v


def _lista(v, onde):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > LISTA_MAX:
        _erro(onde, f"lista com ate {LISTA_MAX} itens")
    return v


def _objeto(v, onde, permitidas):
    if not isinstance(v, dict):
        _erro(onde, "objeto")
    sobra = set(v) - set(permitidas)
    if sobra:
        _erro(onde, "chave desconhecida " + ", ".join(sorted(sobra)) + " (confira a grafia no exemplo)")
    return v


def _faixa(r, onde):
    vmin = _numero(r.get("valor_min"), onde + ".valor_min")
    vmax = _numero(r.get("valor_max"), onde + ".valor_max")
    if vmin is not None and vmax is not None and vmin > vmax:
        _erro(onde, "valor_min maior que valor_max")
    return vmin, vmax


def _trecho(v, onde):
    """Trecho de texto procurado na descricao ja normalizada (minusculo, sem acento)."""
    t = _texto(v, onde, minimo=3)
    return norm(t).strip()


def validar_regras(obj):
    """Devolve as regras normalizadas (trechos em minusculo sem acento, padroes preenchidos) ou levanta ConfigInvalida."""
    _objeto(obj, "regras_privadas", ("titular", "neutros", "entradas", "padroes", "divisoes", "assinaturas_grupos", "_comentario"))
    tit = _objeto(obj.get("titular") or {}, "titular", ("documento", "nomes"))
    doc = tit.get("documento") or ""
    if not isinstance(doc, str) or not re.fullmatch(r"(\d{11}|\d{14})?", doc):
        _erro("titular.documento", "so digitos: 11 (CPF) ou 14 (CNPJ), ou vazio")
    nomes = [_trecho(n, f"titular.nomes[{i}]") for i, n in enumerate(_lista(tit.get("nomes"), "titular.nomes"))]
    if any(len(n) < 4 for n in nomes):
        _erro("titular.nomes", "cada nome precisa de 4+ letras (nome curto casaria com qualquer descricao)")
    out = {"titular": {"documento": doc, "nomes": nomes}}
    out["neutros"] = [_trecho(n, f"neutros[{i}]") for i, n in enumerate(_lista(obj.get("neutros"), "neutros"))]

    out["entradas"] = []
    for i, r in enumerate(_lista(obj.get("entradas"), "entradas")):
        onde = f"entradas[{i}]"
        _objeto(r, onde, ("contem", "tipo", "categoria", "valor_min", "valor_max", "escopo"))
        vmin, vmax = _faixa(r, onde)
        out["entradas"].append({
            "contem": _trecho(r.get("contem"), onde + ".contem"),
            "tipo": _enum(r.get("tipo"), ("receita", "receita_unica", "reembolso", "divida_entrando", "neutro", "estorno"), onde + ".tipo", "receita"),
            "categoria": _texto(r.get("categoria"), onde + ".categoria"),
            "valor_min": vmin, "valor_max": vmax,
            "escopo": _enum(r.get("escopo"), ESCOPOS, onde + ".escopo", "pf"),
        })

    out["padroes"] = []
    for i, r in enumerate(_lista(obj.get("padroes"), "padroes")):
        onde = f"padroes[{i}]"
        _objeto(r, onde, ("contem", "tipo", "categoria", "essencialidade", "valor_min", "valor_max", "escopo"))
        vmin, vmax = _faixa(r, onde)
        tipo = _enum(r.get("tipo"), TIPOS_FLUXO, onde + ".tipo", "gasto")
        ess = _enum(r.get("essencialidade"), ESSENCIALIDADES, onde + ".essencialidade")
        if tipo == "gasto" and ess is None:
            _erro(onde, "gasto precisa de essencialidade")
        out["padroes"].append({
            "contem": _trecho(r.get("contem"), onde + ".contem"), "tipo": tipo,
            "categoria": _texto(r.get("categoria"), onde + ".categoria", opcional=tipo != "gasto"),
            "essencialidade": ess, "valor_min": vmin, "valor_max": vmax,
            "escopo": _enum(r.get("escopo"), ESCOPOS, onde + ".escopo", "pf"),
        })

    out["divisoes"] = []
    for i, r in enumerate(_lista(obj.get("divisoes"), "divisoes")):
        onde = f"divisoes[{i}]"
        _objeto(r, onde, ("contem", "valor_min", "valor_max", "partes"))
        vmin, vmax = _faixa(r, onde)
        partes = []
        for j, p in enumerate(_lista(r.get("partes"), onde + ".partes")):
            op = f"{onde}.partes[{j}]"
            _objeto(p, op, ("proporcao", "tipo", "categoria", "essencialidade", "escopo"))
            prop = _numero(p.get("proporcao"), op + ".proporcao", opcional=False, minimo=0)
            tipo = _enum(p.get("tipo"), TIPOS_FLUXO, op + ".tipo", "gasto")
            ess = _enum(p.get("essencialidade"), ESSENCIALIDADES, op + ".essencialidade")
            if tipo == "gasto" and ess is None:
                _erro(op, "gasto precisa de essencialidade")
            partes.append({"proporcao": prop, "tipo": tipo, "categoria": _texto(p.get("categoria"), op + ".categoria"),
                           "essencialidade": ess, "escopo": _enum(p.get("escopo"), ESCOPOS, op + ".escopo", "pf")})
        if len(partes) < 2 or abs(sum(p["proporcao"] for p in partes) - 1) > 0.001:
            _erro(onde, "partes: 2 ou mais, com proporcoes somando 1")
        out["divisoes"].append({"contem": _trecho(r.get("contem"), onde + ".contem"), "valor_min": vmin, "valor_max": vmax, "partes": partes})

    out["assinaturas_grupos"] = []
    for i, r in enumerate(_lista(obj.get("assinaturas_grupos"), "assinaturas_grupos")):
        onde = f"assinaturas_grupos[{i}]"
        _objeto(r, onde, ("grupo", "contem", "so_valor", "excluir_valor", "esporadica"))
        esp = r.get("esporadica", False)
        if not isinstance(esp, bool):
            _erro(onde + ".esporadica", "true ou false")
        out["assinaturas_grupos"].append({
            "grupo": _texto(r.get("grupo"), onde + ".grupo"), "contem": _trecho(r.get("contem"), onde + ".contem"),
            "so_valor": _numero(r.get("so_valor"), onde + ".so_valor"), "excluir_valor": _numero(r.get("excluir_valor"), onde + ".excluir_valor"),
            "esporadica": esp,
        })
    return out


def _data(v, onde, opcional=True):
    if v is None and opcional:
        return None
    if not isinstance(v, str) or not DATA_ISO.fullmatch(v):
        _erro(onde, "data AAAA-MM-DD")
    return v


def _dia_mes(v, onde):
    if v is None:
        return None
    if not isinstance(v, str) or not DIA_MES.fullmatch(v):
        _erro(onde, "data DD/MM ou DD/MM/AAAA")
    return v


def validar_cadastro(obj):
    """Devolve o cadastro com os padroes preenchidos ou levanta ConfigInvalida."""
    _objeto(obj, "cadastro_manual", ("lido_em", "cartoes", "dividas", "recebiveis", "pontos", "assinaturas", "notas_fiscais", "_comentario"))
    out = {"lido_em": _data(obj.get("lido_em"), "lido_em")}
    out["cartoes"] = []
    for i, c in enumerate(_lista(obj.get("cartoes"), "cartoes")):
        onde = f"cartoes[{i}]"
        _objeto(c, onde, ("fonte", "nome", "limite", "fatura_aberta", "fecha", "vence", "ultima_rotacao"))
        if not isinstance(c.get("fonte"), str) or not FONTE_OK.fullmatch(c["fonte"]):
            _erro(onde + ".fonte", "rotulo [a-z0-9_], o mesmo de PLUGGY_ITEM_IDS")
        out["cartoes"].append({
            "fonte": c["fonte"], "nome": _texto(c.get("nome"), onde + ".nome"),
            "limite": _numero(c.get("limite"), onde + ".limite", minimo=0),
            "fatura_aberta": _numero(c.get("fatura_aberta"), onde + ".fatura_aberta"),
            "fecha": _inteiro(c.get("fecha"), onde + ".fecha", 1, 28), "vence": _inteiro(c.get("vence"), onde + ".vence", 1, 28),
            "ultima_rotacao": _data(c.get("ultima_rotacao"), onde + ".ultima_rotacao"),
        })
    out["dividas"] = []
    for i, d in enumerate(_lista(obj.get("dividas"), "dividas")):
        onde = f"dividas[{i}]"
        _objeto(d, onde, ("nome", "tipo", "saldo", "parcela", "parcelas_total", "parcelas_pagas", "proxima", "nota"))
        item = {
            "nome": _texto(d.get("nome"), onde + ".nome"), "tipo": _enum(d.get("tipo"), ("contrato", "informal"), onde + ".tipo", "contrato"),
            "saldo": _numero(d.get("saldo"), onde + ".saldo", minimo=0), "parcela": _numero(d.get("parcela"), onde + ".parcela", minimo=0),
            "parcelas_total": _inteiro(d.get("parcelas_total"), onde + ".parcelas_total", 1, 1000),
            "parcelas_pagas": _inteiro(d.get("parcelas_pagas"), onde + ".parcelas_pagas", 0, 1000) or 0,
            "proxima": _dia_mes(d.get("proxima"), onde + ".proxima"), "nota": _texto(d.get("nota"), onde + ".nota", 0, True) or "",
        }
        if item["saldo"] is None and (item["parcela"] is None or item["parcelas_total"] is None):
            _erro(onde, "informe saldo, ou parcela e parcelas_total")
        if item["parcelas_total"] is not None and item["parcelas_pagas"] > item["parcelas_total"]:
            _erro(onde, "parcelas_pagas maior que parcelas_total")
        out["dividas"].append(item)
    out["recebiveis"] = []
    for i, r in enumerate(_lista(obj.get("recebiveis"), "recebiveis")):
        onde = f"recebiveis[{i}]"
        _objeto(r, onde, ("nome", "parcela", "parcelas_total", "recebidas", "nota"))
        rec = [_dia_mes(x, f"{onde}.recebidas[{j}]") for j, x in enumerate(_lista(r.get("recebidas"), onde + ".recebidas"))]
        total = _inteiro(r.get("parcelas_total"), onde + ".parcelas_total", 1, 1000, opcional=False)
        if len(rec) > total:
            _erro(onde, "mais recebidas que parcelas_total")
        out["recebiveis"].append({"nome": _texto(r.get("nome"), onde + ".nome"), "parcela": _numero(r.get("parcela"), onde + ".parcela", False, 0),
                                  "parcelas_total": total, "recebidas": rec, "nota": _texto(r.get("nota"), onde + ".nota", 0, True) or ""})
    out["pontos"] = []
    for i, p in enumerate(_lista(obj.get("pontos"), "pontos")):
        onde = f"pontos[{i}]"
        _objeto(p, onde, ("programa", "pts", "reais", "expira", "nota"))
        out["pontos"].append({"programa": _texto(p.get("programa"), onde + ".programa"), "pts": _numero(p.get("pts"), onde + ".pts", minimo=0),
                              "reais": _numero(p.get("reais"), onde + ".reais", minimo=0), "expira": _dia_mes(p.get("expira"), onde + ".expira"),
                              "nota": _texto(p.get("nota"), onde + ".nota", 0, True) or ""})
    out["assinaturas"] = []
    for i, a in enumerate(_lista(obj.get("assinaturas"), "assinaturas")):
        onde = f"assinaturas[{i}]"
        _objeto(a, onde, ("nome", "contem", "valor", "mensal", "so_valor", "detalhe"))
        mensal = a.get("mensal", True)
        if not isinstance(mensal, bool):
            _erro(onde + ".mensal", "true ou false")
        out["assinaturas"].append({"nome": _texto(a.get("nome"), onde + ".nome"), "contem": _trecho(a.get("contem"), onde + ".contem"),
                                   "valor": _numero(a.get("valor"), onde + ".valor", minimo=0), "mensal": mensal,
                                   "so_valor": _numero(a.get("so_valor"), onde + ".so_valor"), "detalhe": _texto(a.get("detalhe"), onde + ".detalhe", 0, True) or ""})
    nf = obj.get("notas_fiscais")
    out["notas_fiscais"] = None
    if nf is not None:
        _objeto(nf, "notas_fiscais", ("prazo_ir", "itens"))
        itens = []
        for i, it in enumerate(_lista(nf.get("itens"), "notas_fiscais.itens")):
            onde = f"notas_fiscais.itens[{i}]"
            _objeto(it, onde, ("descricao", "tem_nota", "sobe_sozinho"))
            if not isinstance(it.get("tem_nota"), bool) or not isinstance(it.get("sobe_sozinho", False), bool):
                _erro(onde, "tem_nota e sobe_sozinho sao true ou false")
            itens.append({"descricao": _texto(it.get("descricao"), onde + ".descricao"), "tem_nota": it["tem_nota"], "sobe_sozinho": it.get("sobe_sozinho", False)})
        out["notas_fiscais"] = {"prazo_ir": _data(nf.get("prazo_ir"), "notas_fiscais.prazo_ir", opcional=False), "itens": itens}
    return out


def _carregar(nome, validar, exemplo):
    caminho = os.path.join(RAIZ, "data", nome)
    if not os.path.exists(caminho):
        raise SystemExit(f"Falta data/{nome}. Copie exemplos/{exemplo} pra data/{nome} e preencha com os seus dados.")
    try:
        with open(caminho, encoding="utf-8") as f:
            obj = json.load(f)
    except ValueError as e:
        raise SystemExit(f"data/{nome} nao e JSON valido: {e}")
    try:
        return validar(obj)
    except ConfigInvalida as e:
        raise SystemExit(f"data/{nome} invalido em {e}")


def carregar_regras():
    return _carregar("regras_privadas.json", validar_regras, "regras_privadas.exemplo.json")


def carregar_cadastro():
    return _carregar("cadastro_manual.json", validar_cadastro, "cadastro_manual.exemplo.json")
