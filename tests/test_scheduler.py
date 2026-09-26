import http.client
import io
import os
import socket
import stat
import sys
import unittest
from contextlib import redirect_stdout

from _base import TOKEN, WithTempRoot, notify

import scheduler  # noqa: E402


class Doorman(unittest.TestCase):
    def test_progressive_block(self):
        now = [1000.0]
        d = scheduler.Doorman(clock=lambda: now[0])
        for _ in range(4):
            d.failed("1.2.3.4")
        self.assertFalse(d.blocked("1.2.3.4"))
        d.failed("1.2.3.4")
        self.assertTrue(d.blocked("1.2.3.4"))
        self.assertFalse(d.blocked("5.6.7.8"))
        now[0] += 61
        self.assertFalse(d.blocked("1.2.3.4"))
        for _ in range(5):
            d.failed("1.2.3.4")
        now[0] += 61
        self.assertTrue(d.blocked("1.2.3.4"))  # second round: 2 min
        now[0] += 60
        self.assertFalse(d.blocked("1.2.3.4"))
        for _ in range(20):  # 1 h ceiling
            for _ in range(5):
                d.failed("1.2.3.4")
            now[0] += 3601
        self.assertEqual(d.ips["1.2.3.4"][2], scheduler.BLOCK_MAX)


class Webhook(WithTempRoot):
    def setUp(self):
        super().setUp()
        self._old_sched_root = scheduler.ROOT
        scheduler.ROOT = self.root
        with redirect_stdout(io.StringIO()):
            self.srv = scheduler.server({"ALERT_WEBHOOK_TOKEN": TOKEN}, 0, "127.0.0.1")
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        scheduler.ROOT = self._old_sched_root
        super().tearDown()

    def post(self, body="ignore:connection-banco_b", path="/alert", token=TOKEN, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Authorization": f"Bearer {token}"} if token else {}
        h.update(headers or {})
        c.request("POST", path, body=body.encode("utf-8"), headers=h)
        r = c.getresponse()
        result = r.status, r.read().decode("utf-8"), r.getheader("Server")
        c.close()
        return result

    def test_listens_only_where_told(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_valid_tap(self):
        code, text, server = self.post()
        self.assertEqual((code, text), (200, "ok"))
        self.assertNotIn("Python", server or "")
        self.assertEqual(notify.state()["ignored"], ["connection-banco_b"])
        self.assertEqual(stat.S_IMODE(os.stat(notify.state_path()).st_mode), 0o600)

    def test_refusals(self):
        self.assertEqual(self.post(path="/other")[0], 404)
        self.assertEqual(self.post(body="ignore:does-not-exist")[:2], (400, "error"))
        self.assertEqual(self.post(body="delete:connection-banco_b")[0], 400)
        self.assertEqual(self.post(body="ignore:" + "a" * 300)[0], 413)
        self.assertEqual(self.post(headers={"Content-Length": "abc"})[0], 400)
        self.assertEqual(notify.state()["ignored"], [])

    def test_no_content_length(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(f"POST /alert HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n\r\n".encode())
        self.assertIn(b" 411 ", s.recv(200))
        s.close()

    def test_wrong_token_blocks_after_5(self):
        for _ in range(5):
            self.assertEqual(self.post(token="x" * 40)[0], 403)
        self.assertEqual(self.post(token="x" * 40)[0], 429)
        self.assertEqual(self.post()[0], 429)  # blocked even with the right token
        self.assertEqual(self.post(token=None)[0], 429)

    def test_no_token_does_not_pass(self):
        self.assertEqual(self.post(token=None)[0], 403)
        self.assertEqual(self.post(token="")[0], 403)


class Startup(unittest.TestCase):
    def test_server_refuses_short_token(self):
        for t in (None, "", "short"):
            with self.assertRaises(ValueError):
                scheduler.server({"ALERT_WEBHOOK_TOKEN": t}, 0)


class RunLog(WithTempRoot):
    def test_error_goes_to_file_not_log(self):
        self._old_sched_root = scheduler.ROOT
        scheduler.ROOT = self.root
        try:
            with redirect_stdout(io.StringIO()) as out:
                ok = scheduler.run(sys.executable, "-c", "import sys; sys.stderr.write('SECRET 1234'); sys.exit(3)")
        finally:
            scheduler.ROOT = self._old_sched_root
        self.assertFalse(ok)
        self.assertNotIn("SECRET", out.getvalue())
        self.assertIn("code 3", out.getvalue())
        folder = os.path.join(self.root, "data", "logs")
        f = os.path.join(folder, os.listdir(folder)[0])
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        with open(f, encoding="utf-8") as fh:
            self.assertIn("SECRET 1234", fh.read())


if __name__ == "__main__":
    unittest.main()
