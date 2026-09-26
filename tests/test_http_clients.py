import io
import unittest
from contextlib import redirect_stdout

import _base  # noqa: F401
import enrich_cnpj as ec
import fetch_history as fh


class Pagination(unittest.TestCase):
    def test_valid_next(self):
        self.assertEqual(fh.next_page("?accountId=abc-123&after=eyJpZCI6MX0%3D"),
                         "https://api.pluggy.ai/v2/transactions?accountId=abc-123&after=eyJpZCI6MX0%3D")
        self.assertIsNone(fh.next_page(None))
        self.assertIsNone(fh.next_page(""))

    def test_invalid_next_stops(self):
        for bad in ("https://evil.example/x", "/../auth?x=1", "?a=1#frag", "?a=1&b=@evil", "?a b", 123, "?a=1\n"):
            with redirect_stdout(io.StringIO()) as out:
                self.assertIsNone(fh.next_page(bad), bad)
            self.assertIn("warning", out.getvalue())


class Transaction(unittest.TestCase):
    def test_minimum(self):
        good = {"id": "t1", "date": "2026-01-02T00:00:00Z", "amount": -10.5}
        self.assertTrue(fh.transaction_ok(good))
        self.assertTrue(fh.transaction_ok({**good, "amount": 3}))
        for bad in ({**good, "id": 1}, {**good, "date": None}, {**good, "amount": "10"}, {**good, "amount": True},
                    {**good, "amount": float("nan")}, {"id": "t"}, "text", None):
            self.assertFalse(fh.transaction_ok(bad), bad)

    def test_only_valid_keeps_order(self):
        res = [{"id": "a", "date": "d", "amount": 1}, {"id": 2}, {"id": "c", "date": "d", "amount": 2}]
        with redirect_stdout(io.StringIO()):
            self.assertEqual([t["id"] for t in fh.only_valid(res)], ["a", "c"])


class Cnae(unittest.TestCase):
    def test_digits_only(self):
        self.assertEqual(ec.map_cnae(4711302), ("Groceries", "essential_variable"))
        self.assertEqual(ec.map_cnae("4711302"), ("Groceries", "essential_variable"))
        for bad in ("47<script>", "4711-3/02", "４７１１", None, "", "abc"):
            self.assertIsNone(ec.map_cnae(bad), bad)


if __name__ == "__main__":
    unittest.main()
