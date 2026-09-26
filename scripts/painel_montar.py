#!/usr/bin/env python3
"""Injeta data/painel.json em painel_template.html e grava a pagina pronta.

Uso: python3 painel_montar.py [caminho_de_saida]  (padrao: data/painel.html, fora do git)
A pagina pronta tem dado financeiro seu: nunca versionar.

CSP: o script da pagina muda a cada montagem (o dado vai dentro dele), entao o hash sha256 dele e
calculado aqui e entra no lugar de __CSP_SCRIPT_HASH__ na meta do template. Assim a CSP libera so esse
script e o Chart.js do cdnjs (com SRI), sem 'unsafe-inline' pra script.
"""

import base64
import hashlib
import os
import re
import sys

RAIZ = os.path.join(os.path.dirname(__file__), "..")


def montar(tpl, dados):
    assert "__DADOS__" in tpl and "__CSP_SCRIPT_HASH__" in tpl
    html = tpl.replace("__DADOS__", dados.replace("</", "<\\/"))
    inline = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(inline) == 1, "a CSP espera um script inline so"
    h = base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode("ascii")
    return html.replace("__CSP_SCRIPT_HASH__", "sha256-" + h, 1)


def main():
    saida = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "data", "painel.html")
    tpl = open(os.path.join(os.path.dirname(__file__), "painel_template.html"), encoding="utf-8").read()
    dados = open(os.path.join(RAIZ, "data", "painel.json"), encoding="utf-8").read()
    open(saida, "w", encoding="utf-8").write(montar(tpl, dados))
    print(saida, os.path.getsize(saida), "bytes")


if __name__ == "__main__":
    os.umask(0o077)
    main()
