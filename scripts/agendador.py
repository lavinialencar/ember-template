#!/usr/bin/env python3
"""Agendador do Ember pro servidor (NAS ou qualquer maquina ligada): roda a rotina todo dia e recebe o toque nos botoes dos alertas na hora.

Roda dentro do contêiner ember-scripts (Dockerfile.scripts). Faz duas coisas:
1. Todo dia, depois de EMBER_HORA (padrao 09:09, fuso do contêiner): atualizar.py (extrato, regras, alertas,
   push e painel), gerar_carga_sql.py e, se houver psql e POSTGRES_PASSWORD no .env, a carga no Postgres.
2. Servidor HTTP na porta EMBER_PORTA (padrao 8082): POST /alerta com o corpo "acao:chave" (ignorar, adiar ou
   ticktick). E o que os botoes do ntfy chamam quando ALERTA_WEBHOOK_URL esta no .env. Com TICKTICK_TOKEN,
   o botao Criar no TickTick cria a tarefa na hora; sem ele, enfileira em data/alertas_estado.json.

A logica (horario, servidor e estado) tem teste em tests/test_agendador.py.

Seguranca do webhook:
- Sem ALERTA_WEBHOOK_TOKEN de 32+ caracteres o servidor NAO sobe (loga ERRO); so a rotina diaria continua.
  Escolha: a rotina e o que importa e nao depende do webhook, e um webhook sem token aceitaria qualquer POST.
- Escuta em EMBER_BIND (padrao 127.0.0.1, so a propria maquina). No servidor, pra o botao do celular alcancar,
  EMBER_BIND=<IP do servidor no Tailscale> (o 100.x.y.z de `tailscale ip -4`), nunca 0.0.0.0.
- Token comparado com hmac.compare_digest; Content-Length obrigatorio e de ate 256 bytes (411/413);
  5 s de timeout por conexao; um pedido por vez.
- IP que erra o token 5 vezes fica bloqueado 1 min (429), e o bloqueio dobra a cada nova rodada de erros, ate 1 h.
- Respostas sem detalhe; o log nao leva corpo de pedido. Quando um passo da rotina falha, o log diz so o
  script e o codigo de saida; a saida de erro inteira vai pra data/logs/<data>.log (0600, fora do git).
"""

import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "..")
sys.path.insert(0, AQUI)
import notificar  # noqa: E402

TRAVA = threading.Lock()  # o estado dos alertas e um arquivo so: um escritor por vez
CORPO_MAX = 256
FALHAS_ATE_BLOQUEIO = 5
BLOQUEIO_MIN, BLOQUEIO_MAX = 60, 3600  # segundos


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def deve_rodar(agora, hora_txt, ultimo_dia):
    """True quando ja passou da hora de hoje e a rotina de hoje ainda nao rodou."""
    h, m = (int(x) for x in hora_txt.split(":"))
    return (agora.hour, agora.minute) >= (h, m) and ultimo_dia != agora.date().isoformat()


def rodar(*cmd, env_extra=None):
    r = subprocess.run(list(cmd), cwd=RAIZ, capture_output=True, text=True, env={**os.environ, **(env_extra or {})})
    nome = " ".join(os.path.basename(c) for c in cmd[:2])
    if r.returncode == 0:
        log(f"{nome}: ok")
    else:  # a saida pode ter dado financeiro: no log so o nome e o codigo; o resto num arquivo local 0600
        log(f"{nome}: ERRO (codigo {r.returncode}), detalhe em data/logs/")
        guardar_erro(nome, r.stderr or r.stdout or "")
    return r.returncode == 0


def guardar_erro(nome, texto):
    pasta = os.path.join(RAIZ, "data", "logs")
    os.makedirs(pasta, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(pasta, f"{datetime.now():%Y-%m-%d}.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(f"--- {datetime.now():%H:%M:%S} {nome}\n{texto}\n")


def rotina(e):
    with TRAVA:
        extra = [] if (e.get("BACKUP_DESTINO") or os.environ.get("BACKUP_DESTINO")) else ["--sem-backup"]
        if extra:
            log("sem BACKUP_DESTINO: rotina sem backup")
        if not rodar(sys.executable, os.path.join(AQUI, "atualizar.py"), *extra):
            return
        rodar(sys.executable, os.path.join(AQUI, "gerar_carga_sql.py"))
        if shutil.which("psql") and e.get("POSTGRES_PASSWORD"):
            rodar("psql", "-h", e.get("PGHOST", "localhost"), "-U", "ember", "-d", "ember", "-v", "ON_ERROR_STOP=1",
                  "-f", "data/carga.sql", env_extra={"PGPASSWORD": e["POSTGRES_PASSWORD"]})


def criar_tarefa_ticktick(e, alerta):
    """Cria a tarefa pela API aberta do TickTick (NAO TESTADO). Devolve o id ou None."""
    token = e.get("TICKTICK_TOKEN")
    if not token:
        return None
    corpo = {"title": "Ember: " + alerta["titulo"], "content": alerta.get("detalhe", ""), "tags": ["ember"],
             "priority": 5 if alerta.get("nivel") == "vencido" else 3, "isAllDay": True,
             "timeZone": e.get("EMBER_TZ") or os.environ.get("EMBER_TZ") or "America/Sao_Paulo"}
    if e.get("TICKTICK_PROJECT_ID"):
        corpo["projectId"] = e["TICKTICK_PROJECT_ID"]
    if alerta.get("prazo"):
        corpo["dueDate"] = alerta["prazo"] + "T00:00:00+0000"
    req = urllib.request.Request("https://api.ticktick.com/open/v1/task", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read()).get("id")
    except Exception as ex:  # cai na fila (notificar.py --pendentes lista o que falta criar)
        log(f"ticktick falhou ({type(ex).__name__}); fica na fila")
        return None


def tratar_toque(e, corpo):
    """corpo 'acao:chave[,chave]'. Devolve (codigo_http, texto)."""
    with TRAVA, notificar.trava():
        itens = {i["chave"]: i for i in notificar.alertas_atuais()}
        ok = notificar.validar_toque(corpo, itens)
        if not ok:
            return 400, "erro"
        acao, chaves = ok
        st = notificar.estado()
        notificar.aplicar(st, acao, chaves)
        if acao == "ticktick":
            for c in chaves.split(","):
                if c not in st.setdefault("ticktick_criadas", {}):
                    tid = criar_tarefa_ticktick(e, itens[c])
                    if tid:
                        st["ticktick_criadas"][c] = tid
        notificar.salvar(st)
    return 200, "ok"


class Porteiro:
    """Conta erro de token por IP, em memoria. 5 erros: bloqueia 1 min; cada nova rodada dobra, ate 1 h."""

    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self.ips = {}  # ip -> [falhas, bloqueado_ate, proxima_espera]

    def bloqueado(self, ip):
        return self.ips.get(ip, [0, 0, 0])[1] > self.relogio()

    def falhou(self, ip):
        if len(self.ips) > 10000:  # ponytail: limpeza grosseira contra muitos IPs; so o Tailscale alcanca a porta
            self.ips.clear()
        reg = self.ips.setdefault(ip, [0, 0, BLOQUEIO_MIN])
        reg[0] += 1
        if reg[0] >= FALHAS_ATE_BLOQUEIO:
            reg[1] = self.relogio() + reg[2]
            reg[0], reg[2] = 0, min(reg[2] * 2, BLOQUEIO_MAX)

    def acertou(self, ip):
        self.ips.pop(ip, None)


def servidor(e, porta, bind="127.0.0.1"):
    token = e.get("ALERTA_WEBHOOK_TOKEN") or ""
    if len(token) < notificar.TOKEN_MIN:
        raise ValueError("ALERTA_WEBHOOK_TOKEN curto demais")
    esperado = f"Bearer {token}".encode("utf-8")
    porteiro = Porteiro()

    class H(BaseHTTPRequestHandler):
        timeout = 5  # segundos por conexao: cliente lento nao prende o servidor
        server_version = "ember"
        sys_version = ""

        def responder(self, codigo, texto=""):
            self.send_response(codigo)
            self.send_header("Content-Length", str(len(texto)))
            self.send_header("Connection", "close")
            self.end_headers()
            if texto:
                self.wfile.write(texto.encode("utf-8"))

        def do_POST(self):
            ip = self.client_address[0]
            if porteiro.bloqueado(ip):
                return self.responder(429)
            if self.path != "/alerta":
                return self.responder(404)
            if not hmac.compare_digest((self.headers.get("Authorization") or "").encode("utf-8"), esperado):
                porteiro.falhou(ip)
                return self.responder(403)
            porteiro.acertou(ip)
            tamanho = self.headers.get("Content-Length")
            if tamanho is None:
                return self.responder(411)
            if not (tamanho.isascii() and tamanho.isdigit()):
                return self.responder(400)
            if int(tamanho) > CORPO_MAX:
                return self.responder(413)
            try:
                corpo = self.rfile.read(int(tamanho)).decode("utf-8")
                codigo, texto = tratar_toque(e, corpo)
            except Exception as ex:  # nada do pedido no log nem na resposta
                log(f"webhook: falha ({type(ex).__name__})")
                codigo, texto = 500, "erro"
            self.responder(codigo, texto)

        def log_message(self, *a):
            pass

    srv = HTTPServer((bind, porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"webhook dos botoes em {bind}:{porta}")
    return srv


def main():
    os.umask(0o077)
    e = notificar.env()
    if len(e.get("ALERTA_WEBHOOK_TOKEN") or "") < notificar.TOKEN_MIN:
        log(f"ERRO: ALERTA_WEBHOOK_TOKEN ausente ou com menos de {notificar.TOKEN_MIN} caracteres no .env; "
            "o webhook dos botoes NAO sobe. So a rotina diaria roda.")
    else:
        servidor(e, int(e.get("EMBER_PORTA", "8082")), e.get("EMBER_BIND", "127.0.0.1"))
    ultimo = ""
    while True:
        agora = datetime.now()
        if deve_rodar(agora, e.get("EMBER_HORA", "09:09"), ultimo):
            log("rotina diaria")
            ultimo = agora.date().isoformat()
            rotina(e)
        time.sleep(30)


if __name__ == "__main__":
    main()
