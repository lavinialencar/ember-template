import hashlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import checar_dados_pessoais as g  # noqa: E402


def cpf_com_digito(base9):
    """Monta um CPF valido em tempo de execucao (literal valido no arquivo faria a propria trava falhar)."""
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append(sum(v * (n + 1 - i) for i, v in enumerate(d)) * 10 % 11 % 10)
    return "".join(map(str, d))


class Trava(unittest.TestCase):
    def motivos(self, texto):
        return [m for _, m in g.checar_texto(texto)]

    def test_cpf(self):
        valido = cpf_com_digito("529982247")
        self.assertIn("CPF com digito verificador valido", self.motivos(f"doc {valido}"))
        self.assertIn("CPF com digito verificador valido", self.motivos(f"doc {valido[:3]}.{valido[3:6]}.{valido[6:9]}-{valido[9:]}"))
        self.assertEqual(self.motivos("doc 12345678900, 00000000000, tx 1234567890123"), [])

    def test_uuid_email_caminho(self):
        self.assertEqual(self.motivos("banco_a:00000000-0000-4000-8000-00000000000a fulano@example.com"), [])
        self.assertTrue(self.motivos("banco_a:" + "1a2b3c4d" + "-0000-4000-8000-00000000000a"))
        self.assertTrue(self.motivos("contato: alguem@" + "provedor.com.br"))
        self.assertTrue(self.motivos("/Users" + "/fulano/x"))

    def test_denylist_por_hash_com_acento_e_par(self):
        termos = {hashlib.sha256(t.encode()).hexdigest() for t in ("zzqfake", "loja zzq")}
        with mock.patch.object(g, "DENYLIST", termos):
            self.assertTrue(self.motivos("texto com ZZQFAKE no meio"))
            self.assertTrue(self.motivos("a Loja  Zzq abriu"))
            self.assertEqual(self.motivos("loja zzqx"), [])

    def test_repositorio_limpo(self):
        raiz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        with mock.patch.object(sys, "argv", ["x", raiz]), mock.patch("builtins.print"):
            self.assertEqual(g.main(), 0)


if __name__ == "__main__":
    unittest.main()
