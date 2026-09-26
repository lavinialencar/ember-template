# Development

## Run the tests

The tests use only `unittest`, only synthetic data and no network. Each one creates a temporary folder and never touches your `data/`.

```sh
python3 -m unittest discover -s tests -v
```

| File | What it covers |
|---|---|
| `test_config.py` | `PLUGGY_ITEM_IDS`, environment taking precedence over `.env`, validation of the two personal JSON files |
| `test_http_clients.py` | Pluggy pagination, malformed transactions, CNAE (national business activity code) with digits only |
| `test_notify.py` | button replies, push text without names, token that never goes to ntfy.sh, signature, atomic state |
| `test_scheduler.py` | progressive blocking, webhook (bind, token, `Content-Length`), errors that go to the file and not to the log |
| `test_load_sql.py` | escaping hostile text and non-finite numbers in the Postgres load |
| `test_dashboard_build.py` | CSP hash matching the script, and SRI present |
| `test_check_personal_data.py` | the personal data guard, and a clean repository |

After the tests, run the full demo, as CI does:

```sh
python3 scripts/make_demo.py --force
python3 scripts/update.py --no-api --no-push --no-backup
```

`--force` overwrites `data/`. Only use it in a copy of the repository that does not hold your real data.

## The personal data guard

`tools/check_personal_data.py` scans every text file in the repository (except `.git/`, `data/`, `__pycache__/`, `.venv/` and `node_modules/`) and fails if it finds:

- a term from the denylist;
- a CPF (individual taxpayer ID) with a valid check digit;
- a UUID that does not start with the fake prefix `00000000-0000-` (a real itemId is a UUID);
- an email outside `example.com`, `example.org` and `example.net`;
- a macOS user folder path or a synced Google Drive folder path.

```sh
python3 tools/check_personal_data.py
```

The output gives the file, the line and the reason. It never repeats the term it found.

### Why the denylist stores only hashes

The denylist exists to stop the name of a fork's maintainer, their employer, their bank or a document from leaking in a commit. If the list stored the terms as text, the list itself would be the leak: anyone could read in the public repository exactly what you wanted to hide.

So it stores only the SHA-256 of each term. The guard normalizes the text (lowercase, no accents, only `a-z` and `0-9`), hashes each word and each pair of adjacent words, and compares against the list.

To add a term:

```sh
python3 -c "import hashlib;print(hashlib.sha256(b'term in lowercase without accents').hexdigest())"
```

Paste the hash into `DENYLIST`. The term can have one or two words.

The limit: the hash of a common word can be found by guessing (someone hashes a list of names and compares). The denylist protects against publishing by accident, not against someone who really wants to find out what is on it. Do not put anything on the list that is secret on its own, like a password or an account number.

### In a fork

The denylist in this repository protects this repository. In your fork, replace it with your own terms: your name, your employer's, your CPF, your itemIds, the name of your city if you want.

## CI

`.github/workflows/ci.yml` runs on every push and pull request:

1. On Python 3.10 and 3.12: compiles all scripts, runs the tests, runs the demo end to end and checks that `data/dashboard.html` was produced, and runs the personal data guard.
2. `gitleaks` on the full history, looking for secrets.

The actions are pinned by SHA, with read-only permission and no credentials kept in the checkout. Dependabot (`.github/dependabot.yml`) proposes weekly updates for the actions, the compose images and `Dockerfile.scripts`.

## Contribute without leaking data

Before you open a pull request:

- [ ] `python3 -m unittest discover -s tests` passes.
- [ ] `python3 tools/check_personal_data.py` passes.
- [ ] `git status` shows nothing from `data/`, `.env`, `*.pem` or `*.cms`.
- [ ] Example data is made up: "Exemplo" and "Modelo" in names, email at `example.com`, UUID starting with `00000000-0000-`, an invalid CPF like `12345678900`.
- [ ] Screenshots only of the demo (`make_demo.py`), never of your own dashboard.
- [ ] Issues and pull requests contain no excerpt of your `data/`, not "just one line", not even with the amount changed.
- [ ] Personal rules (store, employer, person) stay in your `data/private_rules.json`. Only rules that apply to anyone in Brazil go into the code.

A local hook helps you not forget. Save it as `.git/hooks/pre-commit` and make it executable:

```sh
#!/bin/sh
python3 tools/check_personal_data.py && python3 -m unittest discover -s tests
```

If you have `gitleaks` installed, `gitleaks detect` runs the same scan as CI on your machine.

## Where to make changes

| I want to change | File |
|---|---|
| a generic classification rule | `scripts/classify.py` (`PATTERNS`, `MCC_MAP`, `PLUGGY_MAP`) or `scripts/enrich_cnpj.py` (`CNAE`) |
| an alert | `scripts/alerts.py`; the push text in `scripts/notify.py` (`TITLES`) |
| the format of the personal JSON files | `scripts/private_config.py`, the templates in `examples/` and guides 03 and 04 |
| the dashboard | `scripts/dashboard_data.py` (numbers) and `scripts/dashboard_template.html` (visuals) |
| Postgres | a new migration in `sql/`, with the next number |

See also [CONTRIBUTING.md](../CONTRIBUTING.md).
