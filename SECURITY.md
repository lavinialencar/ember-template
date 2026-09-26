# Security policy

## Supported version

Only the `main` branch gets fixes. There are no numbered versions.

## How to report a vulnerability

Report it privately, through GitHub:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the problem, how to reproduce it and the impact you see.

Do not open a public issue, pull request or discussion about the vulnerability before a fix is out.

Do not send real financial data in the report. If you need an example, use the demo (`python3 scripts/make_demo.py`) or made-up data.

## What to expect

- A first reply as soon as someone can read it. The project is maintained by volunteers, with no guaranteed timeline.
- If the vulnerability is confirmed, the fix lands on `main` and the security advisory is published afterwards, with credit to you if you want it.

## Scope

In scope:

- the scripts in `scripts/` and `tools/`;
- the button webhook (`scripts/scheduler.py`) and the button signature (`scripts/notify.py`);
- the generated dashboard (`scripts/dashboard_template.html`, `scripts/dashboard_build.py`): CSP, SRI, escaping;
- the compose files, `Dockerfile.scripts`, the migrations in `sql/` and the workflow in `n8n/`;
- CI in `.github/`;
- the documentation, when it teaches you to do something unsafe.

Out of scope:

- vulnerabilities in Pluggy (Open Finance data aggregator), MeuPluggy (Pluggy's free personal connection app), ntfy, Tailscale, n8n, Postgres, BrasilAPI (free public API for Brazilian data) or TickTick (report them to each maintainer);
- attacks that start from a compromised machine or from your system user (see [docs/09-security.md](docs/09-security.md#what-is-not-protected));
- setups that go against the documentation, like opening a port on `0.0.0.0` or publishing the dashboard.
