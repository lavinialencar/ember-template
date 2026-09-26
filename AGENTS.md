# Instructions for coding assistants

This applies to any AI assistant working in this repository or in a fork of it (Claude Code, Codex, Cursor, Gemini CLI and others).

## Rules that do not bend

- **Never read, print, summarize or copy anything from `data/` or `.env`.** That is where the personal statement, rules and manual records live, and the secrets. This includes `cat`, `head`, `grep`, opening in an editor and running a script that prints the content. If you need data to test, use the demo in a separate copy, or the tests.
- **Never run `make_demo.py --force`** in the folder of someone who uses Ember for real: it overwrites `data/`.
- **Never commit** `data/`, `.env`, `*.pem`, `*.key`, `*.cms` or `data/dashboard.html`. Do not use `git add -f` or `git add -A` without checking `git status`.
- **Never put real data in code, tests, examples, docs, issues or commit messages.** Example data is made up: "Exemplo" and "Modelo" in names, email at `example.com`, UUID starting with `00000000-0000-`, an invalid CPF (individual taxpayer ID).
- **Never change a bind to `0.0.0.0`**, and never suggest opening a port to the internet.
- **Do not call the Pluggy (Open Finance data aggregator) API, ntfy or TickTick** without an explicit request from the user. The scripts do this when run without `--no-api` and `--no-push`.

## Before each commit

```sh
python3 -m unittest discover -s tests
python3 tools/check_personal_data.py
```

Both must pass. If the guard flags something, do not work around it: remove the data.

## Where things live

| What | Where |
|---|---|
| generic classification rules | `scripts/classify.py`, `scripts/enrich_cnpj.py` |
| personal rules | `data/private_rules.json` (do not read); template in `examples/` |
| what the API does not provide | `data/manual_records.json` (do not read); template in `examples/` |
| validation of the two personal JSON files | `scripts/private_config.py` |
| the routine, in order | `scripts/update.py` |
| alerts and push | `scripts/alerts.py`, `scripts/notify.py`, `scripts/suspicious.py` |
| webhook and scheduler | `scripts/scheduler.py` |
| dashboard | `scripts/dashboard_data.py`, `scripts/dashboard_template.html`, `scripts/dashboard_build.py` |
| Postgres | `sql/`, one new migration per change |
| guides | `docs/`, numbered; diagrams in `assets/` |

## Style

- Python with the standard library only. No new dependencies.
- Code, comments and docs in plain English, short sentences.
- The push never carries an amount, or the name of a store, person, card or bank. Keep it that way.
- Changed behavior, update the guide in `docs/` in the same commit.
