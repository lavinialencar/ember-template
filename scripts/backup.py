#!/usr/bin/env python3
"""Encrypted backup of what is not in git: data/ and .env.

Public-key encryption (openssl cms, AES-256): the machine that runs Ember only keeps the
public certificate (BACKUP_CERT, default scripts/backup_cert.pem, which does NOT ship with the repository),
which can only lock. The private key, which unlocks, stays off the machine (password manager).
Without the private key nobody can read the backup, not even whoever finds the file.

Destination: BACKUP_DEST (required), a folder; for example, a folder synced to the cloud.
Keeps the 12 most recent.
"""

import glob
import os
import subprocess
import tarfile
import tempfile
from datetime import date

from fetch_history import load_env

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
KEEP = 12
INCLUDED = ["data", ".env"]


def config():
    env = load_env()
    dest = os.environ.get("BACKUP_DEST") or env.get("BACKUP_DEST")
    if not dest:
        raise SystemExit("Missing BACKUP_DEST in .env (folder where the encrypted backups go). "
                         "To run without a backup: update.py --no-backup")
    cert = os.environ.get("BACKUP_CERT") or env.get("BACKUP_CERT") or os.path.join(HERE, "backup_cert.pem")
    cert = os.path.expanduser(cert)
    if not os.path.exists(cert):
        raise SystemExit(f"Backup public certificate not found ({os.path.basename(cert)}). Set BACKUP_CERT in .env.")
    return os.path.expanduser(dest), cert


def openssl():
    """macOS openssl (LibreSSL) cannot encrypt CMS with an EC certificate. Uses OPENSSL from the environment or the one on PATH, if it is OpenSSL 3."""
    exe = os.environ.get("OPENSSL") or "openssl"
    try:
        version = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        raise SystemExit(f"openssl not found ({exe}). Install OpenSSL 3 (see docs/08-backup.md).")
    if not version.startswith("OpenSSL 3"):
        raise SystemExit(f"Backup needs OpenSSL 3, found: {version.strip() or exe}. On macOS: brew install openssl@3 and "
                         "OPENSSL=$(brew --prefix openssl@3)/bin/openssl (see docs/08-backup.md).")
    return exe


def main():
    dest, cert = config()
    os.makedirs(dest, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "ember.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tar:
            for rel in INCLUDED:
                path = os.path.join(ROOT, rel)
                if os.path.exists(path):
                    tar.add(path, arcname=rel)
        out = os.path.join(dest, f"ember-{date.today().isoformat()}.tar.gz.cms")
        r = subprocess.run(
            [openssl(), "cms", "-encrypt", "-binary", "-aes-256-cbc", "-in", tar_path, "-out", out, "-outform", "DER", cert],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1000:
            print("backup ERROR:", r.stderr[-300:])
            raise SystemExit(1)
    old = sorted(glob.glob(os.path.join(dest, "ember-*.tar.gz.cms")))
    for stale in old[:-KEEP]:
        os.remove(stale)
    print(f"backup: {os.path.basename(out)} ({os.path.getsize(out) // 1024} KB), {min(len(old), KEEP)} kept")


if __name__ == "__main__":
    os.umask(0o077)
    main()
