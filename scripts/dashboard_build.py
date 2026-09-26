#!/usr/bin/env python3
"""Injects data/dashboard.json into dashboard_template.html and writes the finished page.

Usage: python3 dashboard_build.py [output_path]  (default: data/dashboard.html, outside git)
The finished page has your financial data: never commit it.

CSP: the page script changes on every build (the data goes inside it), so its sha256 hash is
computed here and replaces __CSP_SCRIPT_HASH__ in the template's meta tag. That way the CSP allows only this
script and Chart.js from cdnjs (with SRI), with no 'unsafe-inline' for scripts.
"""

import base64
import hashlib
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")


def build(tpl, data):
    assert "__DATA__" in tpl and "__CSP_SCRIPT_HASH__" in tpl
    html = tpl.replace("__DATA__", data.replace("</", "<\\/"))
    inline = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(inline) == 1, "the CSP expects a single inline script"
    h = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode("ascii")
    return html.replace("__CSP_SCRIPT_HASH__", "sha256-" + h, 1)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "dashboard.html")
    tpl = open(os.path.join(os.path.dirname(__file__), "dashboard_template.html"), encoding="utf-8").read()
    data = open(os.path.join(ROOT, "data", "dashboard.json"), encoding="utf-8").read()
    open(out, "w", encoding="utf-8").write(build(tpl, data))
    print(out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    os.umask(0o077)
    main()
