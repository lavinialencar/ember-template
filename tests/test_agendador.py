import http.client
import io
import os
import socket
import stat
import sys
import unittest
from contextlib import redirect_stdout

from _base import TOKEN, ComRaizTemp, notificar

import agendador  # noqa: E402


class Porteiro(unittest.TestCase):
    def test_bloqueio_progressivo(self):
        agora = [1000.0]
        p = agendador.Porteiro(relogio=lambda: agora[0])
        for _ in range(4):
            p.falhou("1.2.3.4")
        self.assertFalse(p.bloqueado("1.2.3.4"))
        p.falhou("1.2.3.4")
        self.assertTrue(p.bloqueado("1.2.3.4"))
        self.assertFalse(p.bloqueado("5.6.7.8"))
        agora[0] += 61
        self.assertFalse(p.bloqueado("1.2.3.4"))
        for _ in range(5):
            p.falhou("1.2.3.4")
        agora[0] += 61
        self.assertTrue(p.bloqueado("1.2.3.4"))  # segunda rodada: 2 min
        agora[0] += 60
        self.assertFalse(p.bloqueado("1.2.3.4"))
        for _ in range(20):  # teto de 1 h
            for _ in range(5):
                p.falhou("1.2.3.4")
            agora[0] += 3601
        self.assertEqual(p.ips["1.2.3.4"][2], agendador.BLOQUEIO_MAX)


class Webhook(ComRaizTemp):
    def setUp(self):
        super().setUp()
        self._raiz_ag = agendador.RAIZ
        agendador.RAIZ = self.raiz
        with redirect_stdout(io.StringIO()):
            self.srv = agendador.servidor({"ALERTA_WEBHOOK_TOKEN": TOKEN}, 0, "127.0.0.1")
        self.porta = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        agendador.RAIZ = self._raiz_ag
        super().tearDown()

    def post(self, corpo="ignorar:conexao-banco_b", caminho="/alerta", token=TOKEN, cabecalhos=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        h = {"Authorization": f"Bearer {token}"} if token else {}
        h.update(cabecalhos or {})
        c.request("POST", caminho, body=corpo.encode("utf-8"), headers=h)
        r = c.getresponse()
        resultado = r.status, r.read().decode("utf-8"), r.getheader("Server")
        c.close()
        return resultado

    def test_escuta_so_onde_mandaram(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_toque_valido(self):
        codigo, texto, servidor = self.post()
        self.assertEqual((codigo, texto), (200, "ok"))
        self.assertNotIn("Python", servidor or "")
        self.assertEqual(notificar.estado()["ignorados"], ["conexao-banco_b"])
        self.assertEqual(stat.S_IMODE(os.stat(notificar.caminho_estado()).st_mode), 0o600)

    def test_recusas(self):
        self.assertEqual(self.post(caminho="/outro")[0], 404)
        self.assertEqual(self.post(corpo="ignorar:nao-existe")[:2], (400, "erro"))
        self.assertEqual(self.post(corpo="apagar:conexao-banco_b")[0], 400)
        self.assertEqual(self.post(corpo="ignorar:" + "a" * 300)[0], 413)
        self.assertEqual(self.post(cabecalhos={"Content-Length": "abc"})[0], 400)
        self.assertEqual(notificar.estado()["ignorados"], [])

    def test_sem_content_length(self):
        s = socket.create_connection(("127.0.0.1", self.porta), timeout=10)
        s.sendall(f"POST /alerta HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n\r\n".encode())
        self.assertIn(b" 411 ", s.recv(200))
        s.close()

    def test_token_errado_bloqueia_depois_de_5(self):
        for _ in range(5):
            self.assertEqual(self.post(token="x" * 40)[0], 403)
        self.assertEqual(self.post(token="x" * 40)[0], 429)
        self.assertEqual(self.post()[0], 429)  # bloqueado mesmo com o token certo
        self.assertEqual(self.post(token=None)[0], 429)

    def test_sem_token_nao_passa(self):
        self.assertEqual(self.post(token=None)[0], 403)
        self.assertEqual(self.post(token="")[0], 403)


class Arranque(unittest.TestCase):
    def test_servidor_recusa_token_curto(self):
        for t in (None, "", "curto"):
            with self.assertRaises(ValueError):
                agendador.servidor({"ALERTA_WEBHOOK_TOKEN": t}, 0)


class RodarLog(ComRaizTemp):
    def test_erro_vai_pro_arquivo_e_nao_pro_log(self):
        self._raiz_ag = agendador.RAIZ
        agendador.RAIZ = self.raiz
        try:
            with redirect_stdout(io.StringIO()) as out:
                ok = agendador.rodar(sys.executable, "-c", "import sys; sys.stderr.write('SEGREDO 1234'); sys.exit(3)")
        finally:
            agendador.RAIZ = self._raiz_ag
        self.assertFalse(ok)
        self.assertNotIn("SEGREDO", out.getvalue())
        self.assertIn("codigo 3", out.getvalue())
        pasta = os.path.join(self.raiz, "data", "logs")
        arq = os.path.join(pasta, os.listdir(pasta)[0])
        self.assertEqual(stat.S_IMODE(os.stat(arq).st_mode), 0o600)
        with open(arq, encoding="utf-8") as f:
            self.assertIn("SEGREDO 1234", f.read())


if __name__ == "__main__":
    unittest.main()
