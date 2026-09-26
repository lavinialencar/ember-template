import hashlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import check_personal_data as g  # noqa: E402


def cpf_with_digits(base9):
    """Builds a valid CPF at run time (a valid literal in the file would make the guard itself fail)."""
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append(sum(v * (n + 1 - i) for i, v in enumerate(d)) * 10 % 11 % 10)
    return "".join(map(str, d))


class Guard(unittest.TestCase):
    def reasons(self, text):
        return [m for _, m in g.check_text(text)]

    def test_cpf(self):
        valid = cpf_with_digits("529982247")
        self.assertIn("CPF with a valid check digit", self.reasons(f"doc {valid}"))
        self.assertIn("CPF with a valid check digit", self.reasons(f"doc {valid[:3]}.{valid[3:6]}.{valid[6:9]}-{valid[9:]}"))
        self.assertEqual(self.reasons("doc 12345678900, 00000000000, tx 1234567890123"), [])

    def test_uuid_email_path(self):
        self.assertEqual(self.reasons("banco_a:00000000-0000-4000-8000-00000000000a someone@example.com"), [])
        self.assertTrue(self.reasons("banco_a:" + "1a2b3c4d" + "-0000-4000-8000-00000000000a"))
        self.assertTrue(self.reasons("contact: someone@" + "provider.com.br"))
        self.assertTrue(self.reasons("/Users" + "/someone/x"))

    def test_denylist_by_hash_with_accent_and_pair(self):
        terms = {hashlib.sha256(t.encode()).hexdigest() for t in ("zzqfake", "shop zzq")}
        with mock.patch.object(g, "DENYLIST", terms):
            self.assertTrue(self.reasons("text with ZZQFAKE in the middle"))
            self.assertTrue(self.reasons("the Shop  Zzq opened"))
            self.assertEqual(self.reasons("shop zzqx"), [])

    def test_repository_clean(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        with mock.patch.object(sys, "argv", ["x", root]), mock.patch("builtins.print"):
            self.assertEqual(g.main(), 0)


if __name__ == "__main__":
    unittest.main()
