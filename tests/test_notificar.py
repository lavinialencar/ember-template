import io
import json
import os
import stat
import unittest
from contextlib import redirect_stdout
from unittest import mock

from _base import ALERTAS, TOKEN, ComRaizTemp, notificar

CONHECIDAS = {a["chave"] for a in ALERTAS}


class ValidarToque(unittest.TestCase):
    def test_aceita_chave_conhecida(self):
        self.assertEqual(notificar.validar_toque("ignorar:conexao-banco_b", CONHECIDAS), ("ignorar", "conexao-banco_b"))
        self.assertEqual(notificar.validar_toque("adiar:conexao-banco_b,suspeita-abc-123", CONHECIDAS),
                         ("adiar", "conexao-banco_b,suspeita-abc-123"))

    def test_recusa(self):
        for corpo in ("apagar:conexao-banco_b", "ignorar:", "ignorar:nao-existe", "ignorar:CONEXAO-banco_b",
                      "ignorar:conexao-banco_b,../x", "", None, "ignorar:" + ",".join(["conexao-banco_b"] * 21)):
            self.assertIsNone(notificar.validar_toque(corpo, CONHECIDAS), corpo)

    def test_formato_mesmo_se_conhecida(self):
        self.assertIsNone(notificar.validar_toque("ignorar:a b", {"a b"}))
        self.assertIsNone(notificar.validar_toque("ignorar:ab\n,cd", {"ab\n", "cd"}))


class TextoPush(unittest.TestCase):
    def test_sem_nome_de_comerciante_cartao_ou_banco(self):
        for a in ALERTAS + [{"chave": "minimo-x,minimo-y", "nivel": "atencao", "n": 2, "curtos": ["CARTAO_X", "CARTAO_Z"]}]:
            titulo, corpo = notificar.texto_push(a)
            for proibido in ("CARTAO_X", "CARTAO_Z", "LOJA_Y", "banco_b"):
                self.assertNotIn(proibido, titulo + corpo)
        self.assertEqual(notificar.texto_push(ALERTAS[1])[1], "1 alerta de atenção, confira o painel.")
        self.assertIn("2 alertas de atenção", notificar.texto_push({"chave": "minimo-x", "nivel": "atencao", "n": 2})[1])
        self.assertTrue(notificar.texto_push(ALERTAS[2])[1].startswith("1 alerta vencido"))


class MontarMsg(unittest.TestCase):
    def msg(self, url, **kw):
        with redirect_stdout(io.StringIO()) as out:
            m = notificar.montar_msg(url, "topico", ALERTAS[1], **kw)
        return m, out.getvalue()

    def test_publico_nunca_leva_token(self):
        m, out = self.msg("https://ntfy.sh", token="ntfytoken", webhook="http://100.1.2.3:8082/alerta", webhook_token=TOKEN)
        self.assertNotIn(TOKEN, json.dumps(m))
        self.assertNotIn("ntfytoken", json.dumps(m))
        self.assertIn("aviso", out)
        self.assertEqual({ac["url"] for ac in m["actions"]}, {"https://ntfy.sh/topico-resposta"})
        for ac in m["actions"]:
            corpo, _, sig = ac["body"].rpartition(":")
            self.assertEqual(sig, notificar.assinatura(TOKEN, "topico", corpo))
            self.assertNotIn("headers", ac)

    def test_publico_sem_token_vai_sem_botao(self):
        m, out = self.msg("https://ntfy.sh", webhook_token="curto")
        self.assertNotIn("actions", m)
        self.assertIn("aviso", out)

    def test_proprio_com_webhook_leva_token_no_cabecalho(self):
        m, _ = self.msg("http://nas.tailnet.ts.net:8081", token="ntfytoken", webhook="http://100.1.2.3:8082/alerta", webhook_token=TOKEN)
        self.assertEqual(m["actions"][0]["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(m["actions"][0]["body"], "adiar:minimo-banco_a-2026-10-05")

    def test_eh_publico(self):
        self.assertTrue(notificar.eh_publico("https://ntfy.sh"))
        self.assertTrue(notificar.eh_publico("https://NTFY.sh/"))
        self.assertFalse(notificar.eh_publico("https://ntfy.sh.exemplo.com"))
        self.assertFalse(notificar.eh_publico("http://nas:8081"))


class RespostaFalsa:
    def __init__(self, linhas):
        self.dados = "\n".join(linhas).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.dados


class LerRespostas(ComRaizTemp):
    def rodar(self, linhas, url="https://ntfy.sh", segredo=TOKEN):
        st = notificar.estado()
        with mock.patch.object(notificar.urllib.request, "urlopen", return_value=RespostaFalsa(linhas)) as u, \
                redirect_stdout(io.StringIO()):
            notificar.ler_respostas(url, "topico", st, None, segredo)
        return st, u

    def assinado(self, corpo):
        return corpo + ":" + notificar.assinatura(TOKEN, "topico", corpo)

    def test_publico_so_aceita_assinado_e_conhecido(self):
        linhas = [
            json.dumps({"id": "m1", "event": "message", "message": self.assinado("ignorar:conexao-banco_b")}),
            json.dumps({"id": "m2", "event": "message", "message": "ignorar:minimo-banco_a-2026-10-05"}),  # sem assinatura
            json.dumps({"id": "m3", "event": "message", "message": "ignorar:minimo-banco_a-2026-10-05:" + "0" * 64}),
            json.dumps({"id": "m4", "event": "message", "message": self.assinado("ticktick:nao-existe")}),
            json.dumps({"event": "message", "message": self.assinado("ticktick:suspeita-abc-123")}),  # sem id
            json.dumps({"id": 5, "event": "message", "message": self.assinado("ticktick:suspeita-abc-123")}),
            "isto nao e json",
            json.dumps(["lista"]),
            json.dumps({"id": "m6", "event": "message", "message": self.assinado("adiar:suspeita-abc-123")}),
        ]
        st, _ = self.rodar(linhas)
        self.assertEqual(st["ignorados"], ["conexao-banco_b"])
        self.assertEqual(st["ticktick"], [])
        self.assertIn("suspeita-abc-123", st["adiados"])

    def test_publico_sem_segredo_nem_consulta(self):
        st, u = self.rodar([json.dumps({"id": "m1", "event": "message", "message": "ignorar:conexao-banco_b"})], segredo=None)
        u.assert_not_called()
        self.assertEqual(st["ignorados"], [])

    def test_proprio_aceita_sem_assinatura(self):
        st, _ = self.rodar([json.dumps({"id": "m1", "event": "message", "message": "ticktick:conexao-banco_b"})],
                           url="http://nas:8081", segredo=None)
        self.assertEqual(st["ticktick"], ["conexao-banco_b"])


class MainDryRun(ComRaizTemp):
    def test_dry_run_ponta_a_ponta_sem_rede(self):
        with open(os.path.join(self.raiz, ".env"), "w") as f:
            f.write("NTFY_TOPIC=topico\nALERTA_WEBHOOK_TOKEN=" + TOKEN + "\n")
        with mock.patch.object(notificar.sys, "argv", ["notificar.py", "--dry-run"]), \
                mock.patch.object(notificar.urllib.request, "urlopen", side_effect=AssertionError("rede")), \
                redirect_stdout(io.StringIO()) as out:
            notificar.main()
        saida = out.getvalue()
        self.assertIn("3 a enviar", saida)
        for proibido in ("CARTAO_X", "LOJA_Y", "banco_b"):
            self.assertNotIn(proibido, saida)


class Estado(ComRaizTemp):
    def test_salvar_atomico_0600_e_com_teto(self):
        st = notificar.estado()
        st["ignorados"] = [f"k{i}" for i in range(900)]
        st["respostas_lidas"] = [f"m{i}" for i in range(900)]
        st["adiados"] = {f"k{i}": "2026-01-01" for i in range(900)}
        with notificar.trava():
            notificar.salvar(st)
        caminho = notificar.caminho_estado()
        self.assertEqual(stat.S_IMODE(os.stat(caminho).st_mode), 0o600)
        de_novo = notificar.estado()
        self.assertEqual(len(de_novo["ignorados"]), notificar.MAX_LISTA)
        self.assertEqual(de_novo["ignorados"][-1], "k899")
        self.assertEqual(len(de_novo["respostas_lidas"]), notificar.MAX_LISTA)
        self.assertEqual(len(de_novo["adiados"]), notificar.MAX_LISTA)
        self.assertEqual([n for n in os.listdir(os.path.join(self.raiz, "data")) if n.startswith(".tmp-")], [])

    def test_gravacao_que_falha_nao_estraga_o_arquivo(self):
        notificar.salvar(notificar.estado())
        caminho = notificar.caminho_estado()
        antes = open(caminho).read()
        with self.assertRaises(TypeError):
            notificar.gravar_json(caminho, {"x": object()})
        self.assertEqual(open(caminho).read(), antes)
        self.assertEqual([n for n in os.listdir(os.path.join(self.raiz, "data")) if n.startswith(".tmp-")], [])


if __name__ == "__main__":
    unittest.main()
