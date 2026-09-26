# Contributing

Thanks for wanting to help. A few short rules:

1. **Never use real data.** Not yours, not anyone's. Use the demo (`python3 scripts/make_demo.py`) and made-up data: names with "Exemplo" or "Modelo", email at `example.com`, UUID starting with `00000000-0000-`, an invalid CPF (individual taxpayer ID).
2. **Python standard library only.** The scripts have no third-party dependencies, and that is on purpose.
3. **Generic rules in code, personal rules in JSON.** What applies to anyone in Brazil goes in `scripts/`. What depends on who you are goes in `data/private_rules.json`, which is never pushed.
4. **Before you open the pull request:**

   ```sh
   python3 -m unittest discover -s tests
   python3 tools/check_personal_data.py
   ```

   Both must pass. CI runs the same ones, plus the demo end to end and `gitleaks`.
5. **Changed behavior, change the guide.** The documentation lives in `docs/`. Diagrams go in `assets/`, as hand-written SVG.
6. **Plain English**, short sentences, second person.

Security vulnerabilities do not go in issues: see [SECURITY.md](SECURITY.md).

The full walkthrough is in [docs/10-development.md](docs/10-development.md).
