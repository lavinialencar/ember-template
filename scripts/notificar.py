#!/usr/bin/env python3
"""Manda os alertas do Ember pro celular pelo ntfy, com botoes: Lembrar amanha, Ignorar e Criar no TickTick
(na compra estranha: Fui eu e Nao fui eu).

Le data/alertas.json (gerado por alertas.py). O push nunca leva valor em reais nem nome de pessoa:
o texto completo fica so no painel. Enquanto o ntfy estiver no servidor publico (ntfy.sh), o topico
e um segredo (NTFY_TOPIC no .env, longo e aleatorio). Com ntfy proprio (docker-compose.ntfy.yml), muda so
NTFY_URL (e NTFY_TOKEN, se o ntfy proprio pedir login).

Os botoes postam num segundo topico (<topico>-resposta). Este script le as respostas na proxima
rodada: "ignorar" para de cobrar aquele alerta; "ticktick" enfileira em data/alertas_estado.json
pra virar tarefa (na hora pelo agendador.py com TICKTICK_TOKEN, ou depois, a partir de --pendentes).

Seguranca:
- O push nao leva nome de comerciante, de cartao nem de banco: so o tipo do alerta, quantos e o nivel.
- No ntfy.sh publico qualquer um que saiba o topico de resposta consegue postar nele. Por isso, la, o corpo
  de cada botao leva uma assinatura HMAC-SHA256 feita com ALERTA_WEBHOOK_TOKEN ("acao:chaves:assinatura"),
  e resposta sem assinatura valida e ignorada. Sem ALERTA_WEBHOOK_TOKEN (32+ caracteres) no .env, o push
  sai sem botoes e as respostas nao sao lidas. O token em si nunca vai pro ntfy.sh: o botao que chama o
  webhook (ALERTA_WEBHOOK_URL, com o token no cabecalho) so existe com ntfy proprio (NTFY_URL fora do ntfy.sh).
- Toda resposta so vale pra chave que existe em data/alertas.json, no formato [a-z0-9_-], ate 20 por toque.
- data/alertas_estado.json e gravado atomico (arquivo temporario + os.replace, 0600) e sob trava
  (fcntl.flock em data/.alertas.lock), porque o agendador.py e este script escrevem nele.

Uso: python3 notificar.py             (le respostas e envia o que for novo)
     python3 notificar.py --dry-run   (mostra o que enviaria, sem enviar)
     python3 notificar.py --pendentes (lista o que voce mandou criar no TickTick)
     python3 notificar.py --criada CHAVE ID (registra a tarefa criada, pra nao criar de novo)
"""

import fcntl
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta
from urllib.parse import urlparse

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HOJE = date.today()
REENVIO_DIAS = {"vencido": 3, "atencao": 7}  # info nao vira push, fica no painel
ACOES = ("ignorar", "adiar", "ticktick")
CHAVE_OK = re.compile(r"^[a-z0-9_-]{1,80}$")
MAX_CHAVES = 20  # por toque
MAX_LISTA = 500  # ignorados, adiados e respostas_lidas guardam so os ultimos
TOKEN_MIN = 32


def env():
    e = {}
    caminho = os.path.join(RAIZ, ".env")
    if os.path.exists(caminho):
        for linha in open(caminho, encoding="utf-8"):
            if "=" in linha and not linha.strip().startswith("#"):
                k, v = linha.strip().split("=", 1)
                e[k] = v.strip().strip('"')
    return e


def caminho_estado():
    return os.path.join(RAIZ, "data", "alertas_estado.json")


@contextmanager
def trava():
    """Trava entre processos (agendador e notificar) em volta de ler, mudar e gravar o estado."""
    os.makedirs(os.path.join(RAIZ, "data"), exist_ok=True)
    fd = os.open(os.path.join(RAIZ, "data", ".alertas.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # fechar solta a trava


def gravar_json(caminho, obj):
    """Grava atomico: temporario na mesma pasta (0600), fsync e os.replace. Nunca deixa arquivo pela metade."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(caminho), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def estado():
    caminho = caminho_estado()
    base = {"enviados": {}, "ignorados": [], "ticktick": [], "adiados": {}, "respostas_lidas": []}
    if os.path.exists(caminho):
        base.update(json.load(open(caminho, encoding="utf-8")))
    return base


def salvar(st):
    st["ignorados"] = st["ignorados"][-MAX_LISTA:]
    st["respostas_lidas"] = st["respostas_lidas"][-MAX_LISTA:]
    st["adiados"] = dict(list(st["adiados"].items())[-MAX_LISTA:])
    gravar_json(caminho_estado(), st)


def alertas_atuais():
    caminho = os.path.join(RAIZ, "data", "alertas.json")
    return json.load(open(caminho, encoding="utf-8"))["itens"] if os.path.exists(caminho) else []


def validar_toque(corpo, conhecidas):
    """corpo 'acao:chave[,chave]'. Devolve (acao, 'chave,chave') so com chaves validas e conhecidas, ou None."""
    acao, _, chaves = (corpo or "").strip().partition(":")
    lista = [c for c in chaves.split(",") if c]
    if acao not in ACOES or not lista or len(lista) > MAX_CHAVES:
        return None
    if not all(CHAVE_OK.fullmatch(c) and c in conhecidas for c in lista):
        return None
    return acao, ",".join(lista)


def eh_publico(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "ntfy.sh" or host.endswith(".ntfy.sh")


def assinatura(segredo, topico, texto):
    return hmac.new(segredo.encode("utf-8"), f"{topico}|{texto}".encode("utf-8"), hashlib.sha256).hexdigest()


def segredo_ok(segredo):
    return bool(segredo) and len(segredo) >= TOKEN_MIN


TITULOS = (
    ("faturas-vencidas", "Ember: fatura vencida em aberto"), ("fatura-fechando", "Ember: fatura fechando"),
    ("minimo-", "Ember: cartão vencendo"), ("conexao-", "Ember: conexão parada"), ("divida-", "Ember: dívida vencendo"),
    ("limite-", "Ember: limite de cartão comprometido"), ("assinatura-", "Ember: assinatura pra conferir"),
    ("suspeita-", "Ember: compra estranha no cartão"), ("rotacao-", "Ember: hora de trocar o cartão"),
    ("recebivel-", "Ember: recebível atrasado"), ("notas-faltando", "Ember: nota fiscal faltando"),
    ("pontos-", "Ember: pontos vencendo"),
)


def texto_push(a):
    """Titulo e corpo do push: so o tipo, quantos e o nivel. Nada de valor, pessoa, comerciante, cartao ou banco
    (o push passa pelo ntfy.sh e aparece na tela bloqueada); o detalhe fica no painel."""
    titulo = next((t for p, t in TITULOS if a["chave"].startswith(p)), "Ember: alerta novo")
    n = a.get("n", 1)
    if a.get("nivel") == "vencido":
        corpo = "1 alerta vencido" if n == 1 else f"{n} alertas vencidos"
    else:
        corpo = "1 alerta de atenção" if n == 1 else f"{n} alertas de atenção"
    corpo += ", confira o painel."
    if a["chave"].startswith("suspeita-"):
        corpo += " Se não foi você, bloqueie o cartão no app do banco."
    return titulo, corpo


def cabecalhos(token, extra=None):
    h = dict(extra or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def montar_msg(url, topico, a, token=None, webhook=None, webhook_token=None):
    titulo, corpo = texto_push(a)
    msg = {
        "topic": topico,
        "title": titulo,
        "message": corpo,
        "tags": ["ember", "warning" if a["nivel"] == "vencido" else "bell"],
        "priority": 4 if a["nivel"] == "vencido" else 3,
    }
    botoes = [("Lembrar amanhã", "adiar"), ("Ignorar", "ignorar"), ("Criar no TickTick", "ticktick")]
    if a["chave"].startswith("suspeita-"):  # aqui o toque tem outro sentido: "Fui eu" ensina, "Nao fui eu" vira tarefa urgente
        botoes = [("Fui eu", "ignorar"), ("Não fui eu", "ticktick")]
        msg["priority"] = 5
        msg["tags"] = ["ember", "rotating_light"]
    if eh_publico(url):
        # ntfy.sh publico: nenhum token vai na mensagem. O botao posta no topico de resposta com o corpo assinado.
        if webhook:
            print("  aviso: ALERTA_WEBHOOK_URL ignorado com o ntfy.sh publico (o token iria junto na mensagem)")
        if segredo_ok(webhook_token):
            resp = f"{url}/{topico}-resposta"
            msg["actions"] = [{"action": "http", "label": rot, "url": resp, "method": "POST", "clear": True,
                               "body": f"{ac}:{a['chave']}:{assinatura(webhook_token, topico, ac + ':' + a['chave'])}"}
                              for rot, ac in botoes]
        else:
            print(f"  aviso: sem ALERTA_WEBHOOK_TOKEN de {TOKEN_MIN}+ caracteres, o push vai sem botoes no ntfy.sh publico")
    else:  # ntfy proprio: o botao pode chamar o webhook com o token no cabecalho
        resp = webhook or f"{url}/{topico}-resposta"
        msg["actions"] = [{"action": "http", "label": rot, "url": resp, "method": "POST", "body": f"{ac}:{a['chave']}", "clear": True}
                          for rot, ac in botoes]
        alvo_token = webhook_token if webhook else token  # cada destino tem o seu token
        if alvo_token:
            for ac in msg["actions"]:
                ac["headers"] = cabecalhos(alvo_token)
    return msg


def publicar(url, topico, a, dry, token=None, webhook=None, webhook_token=None):
    msg = montar_msg(url, topico, a, token, webhook, webhook_token)
    titulo, corpo = msg["title"], msg["message"]
    if dry:
        print(f"  [dry-run] {titulo} | {corpo}")
        return
    req = urllib.request.Request(url, data=json.dumps(msg).encode("utf-8"), headers=cabecalhos(token, {"Content-Type": "application/json"}))
    urllib.request.urlopen(req, timeout=30).read()
    print(f"  enviado: {titulo}")


def aplicar(st, acao, chaves):
    """Efeito de um toque de botao. chaves: uma ou varias separadas por virgula. Devolve quantas mudaram."""
    novas = 0
    for chave in chaves.split(","):
        if not chave:
            continue
        if acao == "ignorar" and chave not in st["ignorados"]:
            st["ignorados"].append(chave)
            novas += 1
        elif acao == "ticktick" and chave not in st["ticktick"]:
            st["ticktick"].append(chave)
            novas += 1
        elif acao == "adiar":
            st["adiados"].pop(chave, None)  # reinsere no fim: o corte de MAX_LISTA tira os mais antigos
            st["adiados"][chave] = (HOJE + timedelta(days=1)).isoformat()
            novas += 1
    return novas


def ler_respostas(url, topico, st, token=None, segredo=None):
    publico = eh_publico(url)
    if publico and not segredo_ok(segredo):
        print("  respostas nao lidas: ntfy.sh publico sem ALERTA_WEBHOOK_TOKEN pra conferir a assinatura")
        return
    novas = 0
    try:
        req = urllib.request.Request(f"{url}/{topico}-resposta/json?poll=1&since=all", headers=cabecalhos(token))
        with urllib.request.urlopen(req, timeout=30) as r:
            linhas = r.read().decode("utf-8").splitlines()
    except Exception as e:
        print(f"  sem resposta do ntfy ({type(e).__name__})")
        return
    conhecidas = {a["chave"] for a in alertas_atuais()}
    recusadas = 0
    for linha in linhas:
        try:
            m = json.loads(linha)
        except ValueError:
            continue
        mid = m.get("id") if isinstance(m, dict) else None
        if not isinstance(mid, str) or m.get("event") != "message" or mid in st["respostas_lidas"]:
            continue
        st["respostas_lidas"].append(mid)
        corpo = m.get("message") if isinstance(m.get("message"), str) else ""
        if publico:
            corpo, _, sig = corpo.rpartition(":")
            if not hmac.compare_digest(sig, assinatura(segredo, topico, corpo)):
                recusadas += 1
                continue
        ok = validar_toque(corpo, conhecidas)
        if not ok:
            recusadas += 1
            continue
        novas += aplicar(st, *ok)
    print(f"respostas novas: {novas}" + (f" (recusadas: {recusadas})" if recusadas else ""))


def main():
    with trava():
        _main()


def _main():
    st = estado()
    if "--criada" in sys.argv:  # --criada CHAVE ID_DA_TAREFA: registra que a tarefa do TickTick foi criada
        i = sys.argv.index("--criada")
        st.setdefault("ticktick_criadas", {})[sys.argv[i + 1]] = sys.argv[i + 2]
        salvar(st)
        print("registrado:", sys.argv[i + 1])
        return
    if "--pendentes" in sys.argv:
        falta = [c for c in st["ticktick"] if c not in st.get("ticktick_criadas", {})]
        print("Pra criar no TickTick:", ", ".join(falta) or "nada")
        return
    dry = "--dry-run" in sys.argv
    e = env()
    url = e.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
    topico = e.get("NTFY_TOPIC")
    token = e.get("NTFY_TOKEN")
    if not topico:
        raise SystemExit("Falta NTFY_TOPIC no .env (um nome longo e aleatorio, o mesmo assinado no app do ntfy).")
    if "--respostas" in sys.argv:
        ler_respostas(url, topico, st, token, e.get("ALERTA_WEBHOOK_TOKEN"))
        salvar(st)
        print("ignorados:", st["ignorados"], "| pra TickTick:", st["ticktick"])
        return
    if "--teste" in sys.argv:
        publicar(url, topico, {"chave": "teste", "nivel": "atencao", "titulo": "Teste do Ember", "curto": "Teste"}, False, token, e.get("ALERTA_WEBHOOK_URL"), e.get("ALERTA_WEBHOOK_TOKEN"))
        return
    if not dry:
        ler_respostas(url, topico, st, token, e.get("ALERTA_WEBHOOK_TOKEN"))
    alertas = json.load(open(os.path.join(RAIZ, "data", "alertas.json"), encoding="utf-8"))["itens"]
    enviados = 0
    fila = []
    for a in alertas:
        if not a.get("acao") or REENVIO_DIAS.get(a["nivel"]) is None or a["chave"] in st["ignorados"] or a["chave"] in st["ticktick"]:
            continue
        ate = st["adiados"].get(a["chave"])
        if ate and ate > HOJE.isoformat():
            continue  # adiado pra depois de hoje
        if ate:  # o adiamento venceu: volta a avisar hoje
            st["adiados"].pop(a["chave"], None)
            st["enviados"].pop(a["chave"], None)
        fila.append(a)
    # avisos parecidos viram um so (dividas vencendo, cartoes vencendo)
    for prefixo in ("divida-", "minimo-", "limite-", "assinatura-", "rotacao-"):
        grupo = [a for a in fila if a["chave"].startswith(prefixo)]
        if len(grupo) > 1:
            fila = [a for a in fila if a not in grupo] + [{"chave": ",".join(a["chave"] for a in grupo), "nivel": "atencao", "acao": True,
                                                            "n": len(grupo), "curtos": [a.get("curto", "") for a in grupo]}]
    for a in fila:
        dias = REENVIO_DIAS[a["nivel"]]
        ultimo = st["enviados"].get(a["chave"])
        if ultimo and date.fromisoformat(ultimo) + timedelta(days=dias) > HOJE:
            continue
        publicar(url, topico, a, dry, token, e.get("ALERTA_WEBHOOK_URL"), e.get("ALERTA_WEBHOOK_TOKEN"))
        if not dry:
            st["enviados"][a["chave"]] = HOJE.isoformat()
        enviados += 1
    if not dry:
        salvar(st)
    print(f"notificar: {enviados} {'a enviar' if dry else 'enviados'}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
