import io
import unittest
from contextlib import redirect_stdout

import _base  # noqa: F401
import baixar_historico as b
import enriquecer_cnpj as ec


class Paginacao(unittest.TestCase):
    def test_next_valido(self):
        self.assertEqual(b.proxima_pagina("?accountId=abc-123&after=eyJpZCI6MX0%3D"),
                         "https://api.pluggy.ai/v2/transactions?accountId=abc-123&after=eyJpZCI6MX0%3D")
        self.assertIsNone(b.proxima_pagina(None))
        self.assertIsNone(b.proxima_pagina(""))

    def test_next_invalido_para(self):
        for ruim in ("https://evil.example/x", "/../auth?x=1", "?a=1#frag", "?a=1&b=@evil", "?a b", 123, "?a=1\n"):
            with redirect_stdout(io.StringIO()) as out:
                self.assertIsNone(b.proxima_pagina(ruim), ruim)
            self.assertIn("aviso", out.getvalue())


class Transacao(unittest.TestCase):
    def test_minimo(self):
        boa = {"id": "t1", "date": "2026-01-02T00:00:00Z", "amount": -10.5}
        self.assertTrue(b.transacao_ok(boa))
        self.assertTrue(b.transacao_ok({**boa, "amount": 3}))
        for ruim in ({**boa, "id": 1}, {**boa, "date": None}, {**boa, "amount": "10"}, {**boa, "amount": True},
                     {**boa, "amount": float("nan")}, {"id": "t"}, "texto", None):
            self.assertFalse(b.transacao_ok(ruim), ruim)

    def test_so_validas_mantem_ordem(self):
        res = [{"id": "a", "date": "d", "amount": 1}, {"id": 2}, {"id": "c", "date": "d", "amount": 2}]
        with redirect_stdout(io.StringIO()):
            self.assertEqual([t["id"] for t in b.so_validas(res)], ["a", "c"])


class Cnae(unittest.TestCase):
    def test_so_digitos(self):
        self.assertEqual(ec.mapear(4711302), ("Mercado", "variavel_essencial"))
        self.assertEqual(ec.mapear("4711302"), ("Mercado", "variavel_essencial"))
        for ruim in ("47<script>", "4711-3/02", "４７１１", None, "", "abc"):
            self.assertIsNone(ec.mapear(ruim), ruim)


if __name__ == "__main__":
    unittest.main()
