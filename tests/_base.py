"""Base dos testes: so dado sintetico, numa pasta temporaria. Nada aqui toca data/ nem a rede."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import notificar  # noqa: E402

TOKEN = "t" * 40
ALERTAS = [
    {"chave": "suspeita-abc-123", "nivel": "vencido", "titulo": "Compra estranha no cartao CARTAO_X: LOJA_Y",
     "detalhe": "LOJA_Y", "curto": "CARTAO_X, LOJA_Y (ramo novo).", "acao": True},
    {"chave": "minimo-banco_a-2026-10-05", "nivel": "atencao", "titulo": "t", "detalhe": "d", "curto": "CARTAO_X vence dia 05/10.", "acao": True},
    {"chave": "conexao-banco_b", "nivel": "vencido", "titulo": "Conexao parada: banco_b", "detalhe": "d", "acao": True},
]


class ComRaizTemp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = self.tmp.name
        os.makedirs(os.path.join(self.raiz, "data"))
        with open(os.path.join(self.raiz, "data", "alertas.json"), "w", encoding="utf-8") as f:
            json.dump({"itens": ALERTAS}, f)
        self._raiz_antiga = notificar.RAIZ
        notificar.RAIZ = self.raiz

    def tearDown(self):
        notificar.RAIZ = self._raiz_antiga
        self.tmp.cleanup()
