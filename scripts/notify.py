#!/usr/bin/env python3
"""Sends Ember's alerts to your phone through ntfy, with buttons: Remind me tomorrow, Ignore and Create in TickTick
(on a suspicious purchase: It was me and Not me).

Reads data/alerts.json (written by alerts.py). The push never carries an amount in reais or a person's name:
the full text stays on the dashboard only. While ntfy runs on the public server (ntfy.sh), the topic
is a secret (NTFY_TOPIC in .env, long and random). With your own ntfy (docker-compose.ntfy.yml), only
NTFY_URL changes (and NTFY_TOKEN, if your own ntfy asks for login).

The buttons post to a second topic (<topic>-reply). This script reads the replies on the next
run: "ignore" stops nagging about that alert; "ticktick" queues it in data/alerts_state.json
to become a task (right away through scheduler.py with TICKTICK_TOKEN, or later, from --pending).

Security:
- The push carries no merchant, card or bank name: only the alert type, how many and the level.
- On public ntfy.sh anyone who knows the reply topic can post to it. So, there, the body
  of each button carries an HMAC-SHA256 signature made with ALERT_WEBHOOK_TOKEN ("action:keys:signature"),
  and a reply without a valid signature is ignored. Without ALERT_WEBHOOK_TOKEN (32+ characters) in .env, the push
  goes out without buttons and replies are not read. The token itself never goes to ntfy.sh: the button that calls the
  webhook (ALERT_WEBHOOK_URL, with the token in the header) only exists with your own ntfy (NTFY_URL not on ntfy.sh).
- Every reply only counts for a key that exists in data/alerts.json, in the format [a-z0-9_-], up to 20 per tap.
- data/alerts_state.json is written atomically (temporary file + os.replace, 0600) and under a lock
  (fcntl.flock on data/.alerts.lock), because scheduler.py and this script both write to it.

Usage: python3 notify.py              (reads replies and sends what is new)
       python3 notify.py --dry-run    (shows what it would send, without sending)
       python3 notify.py --pending    (lists what you asked to create in TickTick)
       python3 notify.py --created KEY ID (records the created task, so it is not created again)
       python3 notify.py --replies    (only reads the replies)
       python3 notify.py --test       (sends a test push)
"""

import fcntl
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta
from urllib.parse import urlparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TODAY = date.today()
RESEND_DAYS = {"overdue": 3, "warning": 7}  # info does not become a push, it stays on the dashboard
ACTIONS = ("ignore", "snooze", "ticktick")
KEY_OK = re.compile(r"^[a-z0-9_-]{1,80}$")
MAX_KEYS = 20  # per tap
MAX_LIST = 500  # ignored, snoozed and replies_read keep only the latest
TOKEN_MIN = 32


def env():
    e = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                e[k] = v.strip().strip('"')
    return e


def state_path():
    return os.path.join(ROOT, "data", "alerts_state.json")


@contextmanager
def lock():
    """Cross-process lock (scheduler and notify) around reading, changing and writing the state."""
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    fd = os.open(os.path.join(ROOT, "data", ".alerts.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing releases the lock


def write_json(path, obj):
    """Atomic write: temporary file in the same folder (0600), fsync and os.replace. Never leaves a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def state():
    path = state_path()
    base = {"sent": {}, "ignored": [], "ticktick": [], "snoozed": {}, "replies_read": []}
    if os.path.exists(path):
        base.update(json.load(open(path, encoding="utf-8")))
    return base


def save(st):
    st["ignored"] = st["ignored"][-MAX_LIST:]
    st["replies_read"] = st["replies_read"][-MAX_LIST:]
    st["snoozed"] = dict(list(st["snoozed"].items())[-MAX_LIST:])
    write_json(state_path(), st)


def current_alerts():
    path = os.path.join(ROOT, "data", "alerts.json")
    return json.load(open(path, encoding="utf-8"))["items"] if os.path.exists(path) else []


def validate_tap(body, known):
    """body 'action:key[,key]'. Returns (action, 'key,key') only with valid, known keys, or None."""
    action, _, keys = (body or "").strip().partition(":")
    items = [k for k in keys.split(",") if k]
    if action not in ACTIONS or not items or len(items) > MAX_KEYS:
        return None
    if not all(KEY_OK.fullmatch(k) and k in known for k in items):
        return None
    return action, ",".join(items)


def is_public(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "ntfy.sh" or host.endswith(".ntfy.sh")


def signature(secret, topic, text):
    return hmac.new(secret.encode("utf-8"), f"{topic}|{text}".encode("utf-8"), hashlib.sha256).hexdigest()


def secret_ok(secret):
    return bool(secret) and len(secret) >= TOKEN_MIN


TITLES = (
    ("overdue-bills", "Ember: overdue bill still open"), ("bill-closing", "Ember: bill closing"),
    ("minimum-", "Ember: card due soon"), ("connection-", "Ember: connection stalled"), ("debt-", "Ember: debt due soon"),
    ("limit-", "Ember: card limit maxed out"), ("subscription-", "Ember: subscription to check"),
    ("suspicious-", "Ember: suspicious card purchase"), ("rotation-", "Ember: time to rotate the card"),
    ("receivable-", "Ember: late receivable"), ("missing-receipts", "Ember: tax receipt missing"),
    ("points-", "Ember: points expiring"),
)


def push_text(a):
    """Push title and body: only the type, how many and the level. No amount, person, merchant, card or bank
    (the push goes through ntfy.sh and shows on the lock screen); the detail stays on the dashboard."""
    title = next((t for p, t in TITLES if a["key"].startswith(p)), "Ember: new alert")
    n = a.get("n", 1)
    if a.get("level") == "overdue":
        body = "1 overdue alert" if n == 1 else f"{n} overdue alerts"
    else:
        body = "1 warning alert" if n == 1 else f"{n} warning alerts"
    body += ", check the dashboard."
    if a["key"].startswith("suspicious-"):
        body += " If it was not you, block the card in the bank app."
    return title, body


def headers(token, extra=None):
    h = dict(extra or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def build_msg(url, topic, a, token=None, webhook=None, webhook_token=None):
    title, body = push_text(a)
    msg = {
        "topic": topic,
        "title": title,
        "message": body,
        "tags": ["ember", "warning" if a["level"] == "overdue" else "bell"],
        "priority": 4 if a["level"] == "overdue" else 3,
    }
    buttons = [("Remind me tomorrow", "snooze"), ("Ignore", "ignore"), ("Create in TickTick", "ticktick")]
    if a["key"].startswith("suspicious-"):  # here a tap means something else: "It was me" teaches, "Not me" becomes an urgent task
        buttons = [("It was me", "ignore"), ("Not me", "ticktick")]
        msg["priority"] = 5
        msg["tags"] = ["ember", "rotating_light"]
    if is_public(url):
        # public ntfy.sh: no token goes in the message. The button posts to the reply topic with a signed body.
        if webhook:
            print("  warning: ALERT_WEBHOOK_URL ignored with public ntfy.sh (the token would travel in the message)")
        if secret_ok(webhook_token):
            reply = f"{url}/{topic}-reply"
            msg["actions"] = [{"action": "http", "label": label, "url": reply, "method": "POST", "clear": True,
                               "body": f"{ac}:{a['key']}:{signature(webhook_token, topic, ac + ':' + a['key'])}"}
                              for label, ac in buttons]
        else:
            print(f"  warning: no ALERT_WEBHOOK_TOKEN of {TOKEN_MIN}+ characters, the push goes without buttons on public ntfy.sh")
    else:  # your own ntfy: the button can call the webhook with the token in the header
        reply = webhook or f"{url}/{topic}-reply"
        msg["actions"] = [{"action": "http", "label": label, "url": reply, "method": "POST", "body": f"{ac}:{a['key']}", "clear": True}
                          for label, ac in buttons]
        target_token = webhook_token if webhook else token  # each destination has its own token
        if target_token:
            for ac in msg["actions"]:
                ac["headers"] = headers(target_token)
    return msg


def publish(url, topic, a, dry, token=None, webhook=None, webhook_token=None):
    msg = build_msg(url, topic, a, token, webhook, webhook_token)
    title, body = msg["title"], msg["message"]
    if dry:
        print(f"  [dry-run] {title} | {body}")
        return
    req = urllib.request.Request(url, data=json.dumps(msg).encode("utf-8"), headers=headers(token, {"Content-Type": "application/json"}))
    urllib.request.urlopen(req, timeout=30).read()
    print(f"  sent: {title}")


def apply(st, action, keys):
    """Effect of a button tap. keys: one or several separated by commas. Returns how many changed."""
    changed = 0
    for key in keys.split(","):
        if not key:
            continue
        if action == "ignore" and key not in st["ignored"]:
            st["ignored"].append(key)
            changed += 1
        elif action == "ticktick" and key not in st["ticktick"]:
            st["ticktick"].append(key)
            changed += 1
        elif action == "snooze":
            st["snoozed"].pop(key, None)  # reinsert at the end: the MAX_LIST cut drops the oldest
            st["snoozed"][key] = (TODAY + timedelta(days=1)).isoformat()
            changed += 1
    return changed


def read_replies(url, topic, st, token=None, secret=None):
    public = is_public(url)
    if public and not secret_ok(secret):
        print("  replies not read: public ntfy.sh without ALERT_WEBHOOK_TOKEN to check the signature")
        return
    changed = 0
    try:
        req = urllib.request.Request(f"{url}/{topic}-reply/json?poll=1&since=all", headers=headers(token))
        with urllib.request.urlopen(req, timeout=30) as r:
            lines = r.read().decode("utf-8").splitlines()
    except Exception as e:
        print(f"  no answer from ntfy ({type(e).__name__})")
        return
    known = {a["key"] for a in current_alerts()}
    refused = 0
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        mid = m.get("id") if isinstance(m, dict) else None
        if not isinstance(mid, str) or m.get("event") != "message" or mid in st["replies_read"]:
            continue
        st["replies_read"].append(mid)
        body = m.get("message") if isinstance(m.get("message"), str) else ""
        if public:
            body, _, sig = body.rpartition(":")
            if not hmac.compare_digest(sig, signature(secret, topic, body)):
                refused += 1
                continue
        ok = validate_tap(body, known)
        if not ok:
            refused += 1
            continue
        changed += apply(st, *ok)
    print(f"new replies: {changed}" + (f" (refused: {refused})" if refused else ""))


def main():
    with lock():
        _main()


def _main():
    st = state()
    if "--created" in sys.argv:  # --created KEY TASK_ID: records that the TickTick task was created
        i = sys.argv.index("--created")
        st.setdefault("ticktick_created", {})[sys.argv[i + 1]] = sys.argv[i + 2]
        save(st)
        print("recorded:", sys.argv[i + 1])
        return
    if "--pending" in sys.argv:
        missing = [k for k in st["ticktick"] if k not in st.get("ticktick_created", {})]
        print("To create in TickTick:", ", ".join(missing) or "nothing")
        return
    dry = "--dry-run" in sys.argv
    e = env()
    url = e.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
    topic = e.get("NTFY_TOPIC")
    token = e.get("NTFY_TOKEN")
    if not topic:
        raise SystemExit("Missing NTFY_TOPIC in .env (a long, random name, the same one subscribed in the ntfy app).")
    if "--replies" in sys.argv:
        read_replies(url, topic, st, token, e.get("ALERT_WEBHOOK_TOKEN"))
        save(st)
        print("ignored:", st["ignored"], "| for TickTick:", st["ticktick"])
        return
    if "--test" in sys.argv:
        publish(url, topic, {"key": "test", "level": "warning", "title": "Ember test", "short": "Test"}, False, token, e.get("ALERT_WEBHOOK_URL"), e.get("ALERT_WEBHOOK_TOKEN"))
        return
    if not dry:
        read_replies(url, topic, st, token, e.get("ALERT_WEBHOOK_TOKEN"))
    alerts = json.load(open(os.path.join(ROOT, "data", "alerts.json"), encoding="utf-8"))["items"]
    sent = 0
    queue = []
    for a in alerts:
        if not a.get("action") or RESEND_DAYS.get(a["level"]) is None or a["key"] in st["ignored"] or a["key"] in st["ticktick"]:
            continue
        until = st["snoozed"].get(a["key"])
        if until and until > TODAY.isoformat():
            continue  # snoozed until after today
        if until:  # the snooze ran out: warn again today
            st["snoozed"].pop(a["key"], None)
            st["sent"].pop(a["key"], None)
        queue.append(a)
    # similar warnings become one (debts due, cards due)
    for prefix in ("debt-", "minimum-", "limit-", "subscription-", "rotation-"):
        group = [a for a in queue if a["key"].startswith(prefix)]
        if len(group) > 1:
            queue = [a for a in queue if a not in group] + [{"key": ",".join(a["key"] for a in group), "level": "warning", "action": True,
                                                              "n": len(group), "shorts": [a.get("short", "") for a in group]}]
    for a in queue:
        days = RESEND_DAYS[a["level"]]
        last = st["sent"].get(a["key"])
        if last and date.fromisoformat(last) + timedelta(days=days) > TODAY:
            continue
        publish(url, topic, a, dry, token, e.get("ALERT_WEBHOOK_URL"), e.get("ALERT_WEBHOOK_TOKEN"))
        if not dry:
            st["sent"][a["key"]] = TODAY.isoformat()
        sent += 1
    if not dry:
        save(st)
    print(f"notify: {sent} {'to send' if dry else 'sent'}")


if __name__ == "__main__":
    os.umask(0o077)
    main()
