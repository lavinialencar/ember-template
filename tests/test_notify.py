import io
import json
import os
import stat
import unittest
from contextlib import redirect_stdout
from unittest import mock

from _base import ALERTS, TOKEN, WithTempRoot, notify

KNOWN = {a["key"] for a in ALERTS}


class ValidateTap(unittest.TestCase):
    def test_accepts_known_key(self):
        self.assertEqual(notify.validate_tap("ignore:connection-banco_b", KNOWN), ("ignore", "connection-banco_b"))
        self.assertEqual(notify.validate_tap("snooze:connection-banco_b,suspicious-abc-123", KNOWN),
                         ("snooze", "connection-banco_b,suspicious-abc-123"))

    def test_refuses(self):
        for body in ("delete:connection-banco_b", "ignore:", "ignore:does-not-exist", "ignore:CONNECTION-banco_b",
                     "ignore:connection-banco_b,../x", "", None, "ignore:" + ",".join(["connection-banco_b"] * 21)):
            self.assertIsNone(notify.validate_tap(body, KNOWN), body)

    def test_format_even_if_known(self):
        self.assertIsNone(notify.validate_tap("ignore:a b", {"a b"}))
        self.assertIsNone(notify.validate_tap("ignore:ab\n,cd", {"ab\n", "cd"}))


class PushText(unittest.TestCase):
    def test_no_merchant_card_or_bank_name(self):
        for a in ALERTS + [{"key": "minimum-x,minimum-y", "level": "warning", "n": 2, "shorts": ["CARD_X", "CARD_Z"]}]:
            title, body = notify.push_text(a)
            for forbidden in ("CARD_X", "CARD_Z", "SHOP_Y", "banco_b"):
                self.assertNotIn(forbidden, title + body)
        self.assertEqual(notify.push_text(ALERTS[1])[1], "1 warning alert, check the dashboard.")
        self.assertIn("2 warning alerts", notify.push_text({"key": "minimum-x", "level": "warning", "n": 2})[1])
        self.assertTrue(notify.push_text(ALERTS[2])[1].startswith("1 overdue alert"))


class BuildMsg(unittest.TestCase):
    def msg(self, url, **kw):
        with redirect_stdout(io.StringIO()) as out:
            m = notify.build_msg(url, "topic", ALERTS[1], **kw)
        return m, out.getvalue()

    def test_public_never_carries_token(self):
        m, out = self.msg("https://ntfy.sh", token="ntfytoken", webhook="http://100.1.2.3:8082/alert", webhook_token=TOKEN)
        self.assertNotIn(TOKEN, json.dumps(m))
        self.assertNotIn("ntfytoken", json.dumps(m))
        self.assertIn("warning", out)
        self.assertEqual({ac["url"] for ac in m["actions"]}, {"https://ntfy.sh/topic-reply"})
        for ac in m["actions"]:
            body, _, sig = ac["body"].rpartition(":")
            self.assertEqual(sig, notify.signature(TOKEN, "topic", body))
            self.assertNotIn("headers", ac)

    def test_public_without_token_has_no_buttons(self):
        m, out = self.msg("https://ntfy.sh", webhook_token="short")
        self.assertNotIn("actions", m)
        self.assertIn("warning", out)

    def test_own_with_webhook_carries_token_in_header(self):
        m, _ = self.msg("http://nas.tailnet.ts.net:8081", token="ntfytoken", webhook="http://100.1.2.3:8082/alert", webhook_token=TOKEN)
        self.assertEqual(m["actions"][0]["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(m["actions"][0]["body"], "snooze:minimum-banco_a-2026-10-05")

    def test_is_public(self):
        self.assertTrue(notify.is_public("https://ntfy.sh"))
        self.assertTrue(notify.is_public("https://NTFY.sh/"))
        self.assertFalse(notify.is_public("https://ntfy.sh.example.com"))
        self.assertFalse(notify.is_public("http://nas:8081"))


class FakeResponse:
    def __init__(self, lines):
        self.data = "\n".join(lines).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.data


class ReadReplies(WithTempRoot):
    def run_with(self, lines, url="https://ntfy.sh", secret=TOKEN):
        st = notify.state()
        with mock.patch.object(notify.urllib.request, "urlopen", return_value=FakeResponse(lines)) as u, \
                redirect_stdout(io.StringIO()):
            notify.read_replies(url, "topic", st, None, secret)
        return st, u

    def signed(self, body):
        return body + ":" + notify.signature(TOKEN, "topic", body)

    def test_public_only_accepts_signed_and_known(self):
        lines = [
            json.dumps({"id": "m1", "event": "message", "message": self.signed("ignore:connection-banco_b")}),
            json.dumps({"id": "m2", "event": "message", "message": "ignore:minimum-banco_a-2026-10-05"}),  # no signature
            json.dumps({"id": "m3", "event": "message", "message": "ignore:minimum-banco_a-2026-10-05:" + "0" * 64}),
            json.dumps({"id": "m4", "event": "message", "message": self.signed("ticktick:does-not-exist")}),
            json.dumps({"event": "message", "message": self.signed("ticktick:suspicious-abc-123")}),  # no id
            json.dumps({"id": 5, "event": "message", "message": self.signed("ticktick:suspicious-abc-123")}),
            "this is not json",
            json.dumps(["list"]),
            json.dumps({"id": "m6", "event": "message", "message": self.signed("snooze:suspicious-abc-123")}),
        ]
        st, _ = self.run_with(lines)
        self.assertEqual(st["ignored"], ["connection-banco_b"])
        self.assertEqual(st["ticktick"], [])
        self.assertIn("suspicious-abc-123", st["snoozed"])

    def test_public_without_secret_does_not_even_query(self):
        st, u = self.run_with([json.dumps({"id": "m1", "event": "message", "message": "ignore:connection-banco_b"})], secret=None)
        u.assert_not_called()
        self.assertEqual(st["ignored"], [])

    def test_own_accepts_without_signature(self):
        st, _ = self.run_with([json.dumps({"id": "m1", "event": "message", "message": "ticktick:connection-banco_b"})],
                              url="http://nas:8081", secret=None)
        self.assertEqual(st["ticktick"], ["connection-banco_b"])


class MainDryRun(WithTempRoot):
    def test_dry_run_end_to_end_no_network(self):
        with open(os.path.join(self.root, ".env"), "w") as f:
            f.write("NTFY_TOPIC=topic\nALERT_WEBHOOK_TOKEN=" + TOKEN + "\n")
        with mock.patch.object(notify.sys, "argv", ["notify.py", "--dry-run"]), \
                mock.patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("network")), \
                redirect_stdout(io.StringIO()) as out:
            notify.main()
        output = out.getvalue()
        self.assertIn("3 to send", output)
        for forbidden in ("CARD_X", "SHOP_Y", "banco_b"):
            self.assertNotIn(forbidden, output)


class State(WithTempRoot):
    def test_save_atomic_0600_and_capped(self):
        st = notify.state()
        st["ignored"] = [f"k{i}" for i in range(900)]
        st["replies_read"] = [f"m{i}" for i in range(900)]
        st["snoozed"] = {f"k{i}": "2026-01-01" for i in range(900)}
        with notify.lock():
            notify.save(st)
        path = notify.state_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        again = notify.state()
        self.assertEqual(len(again["ignored"]), notify.MAX_LIST)
        self.assertEqual(again["ignored"][-1], "k899")
        self.assertEqual(len(again["replies_read"]), notify.MAX_LIST)
        self.assertEqual(len(again["snoozed"]), notify.MAX_LIST)
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "data")) if n.startswith(".tmp-")], [])

    def test_failed_write_does_not_break_the_file(self):
        notify.save(notify.state())
        path = notify.state_path()
        before = open(path).read()
        with self.assertRaises(TypeError):
            notify.write_json(path, {"x": object()})
        self.assertEqual(open(path).read(), before)
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, "data")) if n.startswith(".tmp-")], [])


if __name__ == "__main__":
    unittest.main()
