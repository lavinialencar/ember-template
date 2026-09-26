import unittest

import _base  # noqa: F401  (poe scripts/ no caminho)
import gerar_carga_sql as g

HOSTIS = ["O'Reilly", "barra \\ no meio", "fim com barra \\", "\\'; DROP TABLE mart.fluxo; --", "$$ dolar $$",
          "$tag$ x $tag$", "linha1\nlinha2\r\n", "tab\tfim", "nul\x00no meio", "'' duas aspas", "\\\\'", "E'x'",
          ":variavel_psql", "\\copy x from program 'rm -rf /'", "emoji 🙂 e acento ç"]


def ler_literal(sql):
    """Decodifica um E'...' como o Postgres faz (so as regras que q() usa) e exige que o literal acabe no fim."""
    assert sql.startswith("E'"), sql
    i, out = 2, []
    while True:
        ch = sql[i]
        if ch == "\\":
            out.append(sql[i + 1])
            i += 2
        elif ch == "'":
            if i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("'")
                i += 2
            else:
                assert i == len(sql) - 1, "texto escapou do literal: " + sql
                return "".join(out)
        else:
            out.append(ch)
            i += 1


class Literal(unittest.TestCase):
    def test_texto_hostil_volta_igual_e_nao_escapa(self):
        for t in HOSTIS:
            lit = g.q(t)
            self.assertNotIn("\x00", lit)
            self.assertEqual(ler_literal(lit), t.replace("\x00", ""), t)

    def test_numeros(self):
        self.assertEqual(g.q(12.5), "12.5")
        self.assertEqual(g.q(-3), "-3")
        self.assertEqual(g.q(True), "true")
        self.assertEqual(g.q(None), "NULL")
        for ruim in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                g.q(ruim)

    def test_upsert_com_texto_hostil(self):
        linha = g.upsert("mart.fluxo", ["id", "descricao", "valor"], "id", [["id'1", HOSTIS[3], 1.5]])[0]
        self.assertTrue(linha.startswith("INSERT INTO mart.fluxo (id, descricao, valor) VALUES (E'id''1', "))
        self.assertTrue(linha.endswith("ON CONFLICT (id) DO UPDATE SET descricao = EXCLUDED.descricao, valor = EXCLUDED.valor;"))


if __name__ == "__main__":
    unittest.main()
