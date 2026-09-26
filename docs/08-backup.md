# Backup

`scripts/backup.py` packs `data/` and `.env` into a `.tar.gz` and encrypts it with your public key (`openssl cms`, AES-256). The result goes to `BACKUP_DEST`, a folder that can sync to the cloud.

The idea is simple: the machine that runs Ember only has the public certificate, which can lock but cannot unlock. The private key, which unlocks, stays off the machine, in your password manager. Someone who finds the file in the cloud, or steals the machine, cannot read the backup.

## What you need

- OpenSSL 3. Check with `openssl version`.
- On macOS, the system `openssl` is LibreSSL and fails with elliptic curve keys (`error setting recipientinfo`). Install the Homebrew one (`brew install openssl@3`) and put it first in your `PATH`, including in the schedule (see [02-install.md](02-install.md#macos-with-launchd)). Another option: point the `OPENSSL` variable to the right binary (`OPENSSL=$(brew --prefix openssl@3)/bin/openssl`). `backup.py` checks the version before encrypting and stops with a clear message if it is not OpenSSL 3.
- The `ember-scripts` container already ships with OpenSSL 3.

## 1. Generate the key pair

Do this on a trusted computer, in a temporary folder only you can access:

```sh
mkdir -m 700 ~/ember-key && cd ~/ember-key
openssl ecparam -name secp384r1 -genkey -noout -out private.pem
openssl req -new -x509 -key private.pem -out backup_cert.pem -days 3650 -subj "/CN=Ember backup"
```

- `private.pem` is the private key (P-384 curve). It opens the backups.
- `backup_cert.pem` is the self-signed certificate with the public key. It only locks.

## 2. Keep each half in the right place

1. Open `private.pem` and store its full content in your password manager, as a secure note or an attachment.
2. Copy the certificate to the Ember machine:

   ```sh
   cp ~/ember-key/backup_cert.pem /path/to/ember-template/scripts/backup_cert.pem
   ```

   This is the default path. If you prefer another place, set `BACKUP_CERT` in `.env`. `.gitignore` already ignores `*.pem`, `*.key` and `*.cms`.

3. Delete the temporary folder:

   ```sh
   rm -rf ~/ember-key
   ```

The private key must not stay on disk on the Ember machine, not in `data/`, and not in the repository.

## 3. Turn on the backup

In `.env`:

```
BACKUP_DEST=/path/to/backup/folder
```

Test it:

```sh
python3 scripts/backup.py
```

You should see `backup: ember-YYYY-MM-DD.tar.gz.cms (N KB), 1 kept`. Without `BACKUP_DEST` or without the certificate, the script stops with a clear message. To run the routine without a backup: `update.py --no-backup`.

## Retention

- One file per day: `ember-YYYY-MM-DD.tar.gz.cms`. Running twice on the same day overwrites that day's file.
- The 12 most recent are kept. Older ones are deleted on each run.
- With the daily routine, that gives about 12 days of history. If you want to keep more, copy one file per month somewhere else.

## Restore

Test a restore once, right after you set it up. A backup you have never opened is not a backup.

1. Copy the private key from your password manager to a temporary file:

   ```sh
   mkdir -m 700 ~/ember-restore && cd ~/ember-restore
   # paste the content into private.pem, with permission 600
   ```

2. Decrypt and extract:

   ```sh
   openssl cms -decrypt -inform DER -in /path/ember-YYYY-MM-DD.tar.gz.cms -inkey private.pem | tar xz
   ```

   You get `data/` and `.env`, as they were on the day of the backup.

3. Copy `data/` and `.env` into the repository (with Ember stopped) and check the permissions:

   ```sh
   chmod 700 data && chmod 600 .env
   ```

4. Delete the temporary key:

   ```sh
   rm ~/ember-restore/private.pem
   ```

## If you lose the private key

Old backups become unreadable forever. Generate a new pair (step 1), replace the certificate and make a new backup right away.

## If the private key leaks

Generate a new pair, replace the certificate and delete the old backups from the destination: whoever has the old key can open all of them. Also rotate the secrets in `.env`, because it is inside the backup.

Next: [09-security.md](09-security.md).
