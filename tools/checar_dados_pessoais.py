#!/usr/bin/env python3
"""Trava de dado pessoal: falha se o repositorio tiver algum identificador de quem criou o template.

Duas checagens em todo arquivo de texto do repositorio (fora .git/, data/ e __pycache__/):

1. Denylist por hash. Cada palavra e cada par de palavras do texto (minusculo, sem acento, so [a-z0-9])
   vira SHA-256 e e comparado com a lista abaixo. A lista guarda so os hashes: os identificadores em si
   nunca aparecem aqui. Pra acrescentar um termo:  python3 -c "import hashlib;print(hashlib.sha256(b'termo').hexdigest())"
2. Forma de dado pessoal:
   - CPF com digito verificador valido (11 digitos, com ou sem pontuacao; sequencia repetida nao conta);
   - UUID que nao comeca com o prefixo falso 00000000-0000- (itemId de verdade da Pluggy e UUID);
   - e-mail fora de example.com, example.org e example.net;
   - caminho de pasta de usuario do macOS ou de pasta sincronizada do Google Drive.

Uso: python3 tools/checar_dados_pessoais.py [pasta]   (padrao: a raiz do repositorio). Sai com 1 se achar algo.
"""

import hashlib
import os
import re
import sys
import unicodedata

DENYLIST = {
    "bc8a153d21ceefd7f035398cdceb1c08a89d1f7e0f55f73fc4c23b3dda2e5c15",
    "f69a19da14babc8e0ce896ba51717749b80453b361e41c643d007d89ff6815f5",
    "2be096da92977cfc443a05462ab5d772786d4551842015a17da15f5503914ee2",
    "b67bdbc2b8b60278a553e338836c4d28d15ce6f74a85fc7de108bb928eac4e65",
    "5e9feffeb70f6165d7987d6caf493f454b9d5d156cde034457afe039142c8bdf",
    "b6391799bba8d6ba982a1c33ba9af25a590ed1eb4a5570b02a43132918d57e7d",
    "26b47209413e5776b8a32b9ef89bb47312a75875bf475d39a78e5ae4dcc095f3",
    "d1142dde4dbea367d24236439ef906b6cf9ba4beba07548afae7f9bab86cb1b9",
    "b4b31594a67c342cda2a0f94ed6e36a2c72d46a5b4978114217d2411e3516700",
    "b0b69973718b14e91a235c1665c6341c50a877c561b45bb7176aab1287cac5f8",
    "f50a99a1a3db4383bcc808147cca0107bd4f2a6369c0f68f7ad912deab65893c",
    "150c3e7dbc5ec0cc7961fe38c5a54ac5a8e828728af034e7cc4c3a0a96380448",
    "96f4e58785d1e81b8795966eea692030edbcfeae079e296a59de591fcfe0765f",
    "bd9da2a210da3061423d27216c65bbf24a85555ab815efaddd95a3d69dce9fc8",
    "64350bf975ebcc4ba2425a6bce91b126094795c6186e693a08893f0a77b472c0",
    "796283ee70f052944c6a813a6aa226b2a033a7173c19430744f1d81fba32dae1",
    "93a9ca56146f26d4d6aa7ee945d5473ec102eaa43dad8de4290a02bd102a3d26",
    "3d5a08e544dbde50c2ca176a9ce1c3b2222863143268091dba796656de49d4af",
}
PULAR = {".git", "data", "__pycache__", ".venv", "node_modules"}
UUID_FALSO = "00000000-0000-"
EMAIL_OK = ("example.com", "example.org", "example.net")

RE_CPF = re.compile(r"(?<![\d.])(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?![\d.])")
RE_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
RE_CAMINHO = re.compile(r"/Users/[A-Za-z]|Google[D]rive-|Cloud[S]torage/")


def cpf_valido(digitos):
    if len(set(digitos)) == 1:
        return False
    for n in (9, 10):
        soma = sum(int(d) * (n + 1 - i) for i, d in enumerate(digitos[:n]))
        if (soma * 10 % 11) % 10 != int(digitos[n]):
            return False
    return True


def tokens(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    palavras = re.findall(r"[a-z0-9]+", t)
    yield from palavras
    for a, b in zip(palavras, palavras[1:]):
        yield f"{a} {b}"


def checar_texto(texto):
    """Lista de (linha, motivo). Nunca devolve o termo achado, so o motivo."""
    achados = []
    for n, linha in enumerate(texto.splitlines(), 1):
        for tk in tokens(linha):
            if hashlib.sha256(tk.encode()).hexdigest() in DENYLIST:
                achados.append((n, "identificador da denylist"))
                break
        for m in RE_CPF.finditer(linha):
            if cpf_valido("".join(m.groups())):
                achados.append((n, "CPF com digito verificador valido"))
        for m in RE_UUID.finditer(linha):
            if not m.group(0).lower().startswith(UUID_FALSO):
                achados.append((n, "UUID fora do prefixo falso " + UUID_FALSO))
        for m in RE_EMAIL.finditer(linha):
            if m.group(1).lower() not in EMAIL_OK:
                achados.append((n, "e-mail fora de example.com"))
        if RE_CAMINHO.search(linha):
            achados.append((n, "caminho de pasta pessoal"))
    return achados


def arquivos(raiz):
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s not in PULAR]
        for nome in nomes:
            yield os.path.join(pasta, nome)


def main():
    raiz = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    total, lidos = 0, 0
    for caminho in arquivos(raiz):
        try:
            with open(caminho, encoding="utf-8") as f:
                texto = f.read()
        except (UnicodeDecodeError, OSError):
            continue  # binario
        lidos += 1
        rel = os.path.relpath(caminho, raiz)
        for n, motivo in checar_texto(rel + "\n" + texto):
            print(f"{rel}:{n - 1 if n > 1 else 'nome'}: {motivo}")
            total += 1
    print(f"checar_dados_pessoais: {lidos} arquivos, {total} achado(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
