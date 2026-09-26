#!/usr/bin/env python3
"""Ember's scheduler for the server (a NAS or any always-on machine): runs the routine every day and receives alert button taps right away.

Runs inside the ember-scripts container (Dockerfile.scripts). It does two things:
1. Every day, after EMBER_TIME (default 09:09, container time zone): update.py (statement, rules, alerts,
   push and dashboard), build_load_sql.py and, if psql and POSTGRES_PASSWORD are in .env, the Postgres load.
2. HTTP server on port EMBER_PORT (default 8082): POST /alert with the body "action:key" (ignore, snooze or
   ticktick). It is what the ntfy buttons call when ALERT_WEBHOOK_URL is in .env. With TICKTICK_TOKEN,
   the Create in TickTick button creates the task right away; without it, the task is queued in data/alerts_state.json.

The logic (schedule, server and state) is tested in tests/test_scheduler.py.

Webhook security:
- Without an ALERT_WEBHOOK_TOKEN of 32+ characters the server does NOT start (it logs ERROR); only the daily routine goes on.
  The choice: the routine is what matters and it does not depend on the webhook, and a webhook without a token would accept any POST.
- Listens on EMBER_BIND (default 127.0.0.1, the machine itself only). On the server, for the phone button to reach it,
  EMBER_BIND=<server IP on Tailscale> (the 100.x.y.z from `tailscale ip -4`), never 0.0.0.0.
- Token compared with hmac.compare_digest; Content-Length required and at most 256 bytes (411/413);
  5 s timeout per connection; one request at a time.
- An IP that gets the token wrong 5 times is blocked for 1 min (429), and the block doubles with each new round of errors, up to 1 h.
- Responses carry no detail; the log carries no request body. When a routine step fails, the log only says the
  script and the exit code; the full error output goes to data/logs/<date>.log (0600, outside git).
"""

import hmac
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import notify  # noqa: E402

LOCK = threading.Lock()  # the alert state is a single file: one writer at a time
BODY_MAX = 256
FAILS_BEFORE_BLOCK = 5
BLOCK_MIN, BLOCK_MAX = 60, 3600  # seconds


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def should_run(now, time_txt, last_day):
    """True once today's time has passed and today's routine has not run yet."""
    h, m = (int(x) for x in time_txt.split(":"))
    return (now.hour, now.minute) >= (h, m) and last_day != now.date().isoformat()


def run(*cmd, env_extra=None):
    r = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True, env={**os.environ, **(env_extra or {})})
    name = " ".join(os.path.basename(c) for c in cmd[:2])
    if r.returncode == 0:
        log(f"{name}: ok")
    else:  # the output may have financial data: the log gets only the name and the code; the rest goes to a local 0600 file
        log(f"{name}: ERROR (code {r.returncode}), details in data/logs/")
        save_error(name, r.stderr or r.stdout or "")
    return r.returncode == 0


def save_error(name, text):
    folder = os.path.join(ROOT, "data", "logs")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(folder, f"{datetime.now():%Y-%m-%d}.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(f"--- {datetime.now():%H:%M:%S} {name}\n{text}\n")


def routine(e):
    with LOCK:
        extra = [] if (e.get("BACKUP_DEST") or os.environ.get("BACKUP_DEST")) else ["--no-backup"]
        if extra:
            log("no BACKUP_DEST: routine without backup")
        if not run(sys.executable, os.path.join(HERE, "update.py"), *extra):
            return
        run(sys.executable, os.path.join(HERE, "build_load_sql.py"))
        if shutil.which("psql") and e.get("POSTGRES_PASSWORD"):
            run("psql", "-h", e.get("PGHOST", "localhost"), "-U", "ember", "-d", "ember", "-v", "ON_ERROR_STOP=1",
                "-f", "data/load.sql", env_extra={"PGPASSWORD": e["POSTGRES_PASSWORD"]})


def create_ticktick_task(e, alert):
    """Creates the task through TickTick's open API (NOT TESTED). Returns the id or None."""
    token = e.get("TICKTICK_TOKEN")
    if not token:
        return None
    body = {"title": "Ember: " + alert["title"], "content": alert.get("detail", ""), "tags": ["ember"],
            "priority": 5 if alert.get("level") == "overdue" else 3, "isAllDay": True,
            "timeZone": e.get("EMBER_TZ") or os.environ.get("EMBER_TZ") or "America/Sao_Paulo"}
    if e.get("TICKTICK_PROJECT_ID"):
        body["projectId"] = e["TICKTICK_PROJECT_ID"]
    if alert.get("due"):
        body["dueDate"] = alert["due"] + "T00:00:00+0000"
    req = urllib.request.Request("https://api.ticktick.com/open/v1/task", data=json.dumps(body).encode("utf-8"),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read()).get("id")
    except Exception as ex:  # falls back to the queue (notify.py --pending lists what is left to create)
        log(f"ticktick failed ({type(ex).__name__}); it stays in the queue")
        return None


def handle_tap(e, body):
    """body 'action:key[,key]'. Returns (http_code, text)."""
    with LOCK, notify.lock():
        items = {i["key"]: i for i in notify.current_alerts()}
        ok = notify.validate_tap(body, items)
        if not ok:
            return 400, "error"
        action, keys = ok
        st = notify.state()
        notify.apply(st, action, keys)
        if action == "ticktick":
            for k in keys.split(","):
                if k not in st.setdefault("ticktick_created", {}):
                    tid = create_ticktick_task(e, items[k])
                    if tid:
                        st["ticktick_created"][k] = tid
        notify.save(st)
    return 200, "ok"


class Doorman:
    """Counts token errors per IP, in memory. 5 errors: blocks for 1 min; each new round doubles it, up to 1 h."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.ips = {}  # ip -> [failures, blocked_until, next_wait]

    def blocked(self, ip):
        return self.ips.get(ip, [0, 0, 0])[1] > self.clock()

    def failed(self, ip):
        if len(self.ips) > 10000:  # ponytail: crude cleanup against many IPs; only Tailscale reaches the port
            self.ips.clear()
        reg = self.ips.setdefault(ip, [0, 0, BLOCK_MIN])
        reg[0] += 1
        if reg[0] >= FAILS_BEFORE_BLOCK:
            reg[1] = self.clock() + reg[2]
            reg[0], reg[2] = 0, min(reg[2] * 2, BLOCK_MAX)

    def succeeded(self, ip):
        self.ips.pop(ip, None)


def server(e, port, bind="127.0.0.1"):
    token = e.get("ALERT_WEBHOOK_TOKEN") or ""
    if len(token) < notify.TOKEN_MIN:
        raise ValueError("ALERT_WEBHOOK_TOKEN too short")
    expected = f"Bearer {token}".encode("utf-8")
    doorman = Doorman()

    class H(BaseHTTPRequestHandler):
        timeout = 5  # seconds per connection: a slow client does not hold the server
        server_version = "ember"
        sys_version = ""

        def reply(self, code, text=""):
            self.send_response(code)
            self.send_header("Content-Length", str(len(text)))
            self.send_header("Connection", "close")
            self.end_headers()
            if text:
                self.wfile.write(text.encode("utf-8"))

        def do_POST(self):
            ip = self.client_address[0]
            if doorman.blocked(ip):
                return self.reply(429)
            if self.path != "/alert":
                return self.reply(404)
            if not hmac.compare_digest((self.headers.get("Authorization") or "").encode("utf-8"), expected):
                doorman.failed(ip)
                return self.reply(403)
            doorman.succeeded(ip)
            size = self.headers.get("Content-Length")
            if size is None:
                return self.reply(411)
            if not (size.isascii() and size.isdigit()):
                return self.reply(400)
            if int(size) > BODY_MAX:
                return self.reply(413)
            try:
                body = self.rfile.read(int(size)).decode("utf-8")
                code, text = handle_tap(e, body)
            except Exception as ex:  # nothing from the request in the log or in the response
                log(f"webhook: failure ({type(ex).__name__})")
                code, text = 500, "error"
            self.reply(code, text)

        def log_message(self, *a):
            pass

    srv = HTTPServer((bind, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"button webhook on {bind}:{port}")
    return srv


def main():
    os.umask(0o077)
    e = notify.env()
    if len(e.get("ALERT_WEBHOOK_TOKEN") or "") < notify.TOKEN_MIN:
        log(f"ERROR: ALERT_WEBHOOK_TOKEN missing or shorter than {notify.TOKEN_MIN} characters in .env; "
            "the button webhook does NOT start. Only the daily routine runs.")
    else:
        server(e, int(e.get("EMBER_PORT", "8082")), e.get("EMBER_BIND", "127.0.0.1"))
    last = ""
    while True:
        now = datetime.now()
        if should_run(now, e.get("EMBER_TIME", "09:09"), last):
            log("daily routine")
            last = now.date().isoformat()
            routine(e)
        time.sleep(30)


if __name__ == "__main__":
    main()
