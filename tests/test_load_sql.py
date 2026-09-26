import unittest

import _base  # noqa: F401  (puts scripts/ on the path)
import build_load_sql as g

HOSTILE = ["O'Reilly", "backslash \\ in the middle", "ends with backslash \\", "\\'; DROP TABLE mart.flow; --", "$$ dollar $$",
           "$tag$ x $tag$", "line1\nline2\r\n", "tab\tend", "nul\x00in the middle", "'' two quotes", "\\\\'", "E'x'",
           ":psql_variable", "\\copy x from program 'rm -rf /'", "emoji 🙂 and accent ç"]


def read_literal(sql):
    """Decodes an E'...' the way Postgres does (only the rules q() uses) and requires the literal to end at the end."""
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
                assert i == len(sql) - 1, "text escaped the literal: " + sql
                return "".join(out)
        else:
            out.append(ch)
            i += 1


class Literal(unittest.TestCase):
    def test_hostile_text_round_trips_and_does_not_escape(self):
        for t in HOSTILE:
            lit = g.q(t)
            self.assertNotIn("\x00", lit)
            self.assertEqual(read_literal(lit), t.replace("\x00", ""), t)

    def test_numbers(self):
        self.assertEqual(g.q(12.5), "12.5")
        self.assertEqual(g.q(-3), "-3")
        self.assertEqual(g.q(True), "true")
        self.assertEqual(g.q(None), "NULL")
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                g.q(bad)

    def test_upsert_with_hostile_text(self):
        line = g.upsert("mart.flow", ["id", "description", "amount"], "id", [["id'1", HOSTILE[3], 1.5]])[0]
        self.assertTrue(line.startswith("INSERT INTO mart.flow (id, description, amount) VALUES (E'id''1', "))
        self.assertTrue(line.endswith("ON CONFLICT (id) DO UPDATE SET description = EXCLUDED.description, amount = EXCLUDED.amount;"))


if __name__ == "__main__":
    unittest.main()
