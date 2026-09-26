#!/usr/bin/env python3
"""Backup criptografado do que nao esta no git: data/ e .env.

Criptografia por chave publica (openssl cms, AES-256): a maquina que roda o Ember so guarda o
certificado publico (BACKUP_CERT, padrao scripts/backup_cert.pem, que NAO vem no repositorio),
que so sabe trancar. A chave privada, que destranca, fica fora da maquina (gerenciador de senhas).
Sem a chave privada ninguem le o backup, nem quem achar o arquivo.

Destino: BACKUP_DESTINO (obrigatorio), uma pasta; por exemplo, uma pasta sincronizada com a nuvem.
Guarda os 12 mais recentes.
"""

import glob
import os
import subprocess
import tarfile
import tempfile
from datetime import date

from baixar_historico import carregar_env

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(AQUI, "..")
GUARDAR = 12
ENTRAM = ["data", ".env"]


def config():
    env = carregar_env()
    destino = os.environ.get("BACKUP_DESTINO") or env.get("BACKUP_DESTINO")
    if not destino:
        raise SystemExit("Falta BACKUP_DESTINO no .env (pasta onde os backups criptografados vao ficar). "
                         "Pra rodar sem backup: atualizar.py --sem-backup")
    cert = os.environ.get("BACKUP_CERT") or env.get("BACKUP_CERT") or os.path.join(AQUI, "backup_cert.pem")
    cert = os.path.expanduser(cert)
    if not os.path.exists(cert):
        raise SystemExit(f"Certificado publico do backup nao encontrado ({os.path.basename(cert)}). Defina BACKUP_CERT no .env.")
    return os.path.expanduser(destino), cert


def openssl():
    """O openssl do macOS (LibreSSL) nao cifra CMS com certificado EC. Usa OPENSSL do ambiente ou o do PATH, se for OpenSSL 3."""
    exe = os.environ.get("OPENSSL") or "openssl"
    try:
        versao = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        raise SystemExit(f"openssl nao encontrado ({exe}). Instale o OpenSSL 3 (ver docs/08-backup.md).")
    if not versao.startswith("OpenSSL 3"):
        raise SystemExit(f"Backup precisa do OpenSSL 3, achei: {versao.strip() or exe}. No macOS: brew install openssl@3 e "
                         "OPENSSL=$(brew --prefix openssl@3)/bin/openssl (ver docs/08-backup.md).")
    return exe


def main():
    destino, cert = config()
    os.makedirs(destino, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "ember.tar.gz")
        with tarfile.open(tar_path, "w:gz") as tar:
            for rel in ENTRAM:
                caminho = os.path.join(RAIZ, rel)
                if os.path.exists(caminho):
                    tar.add(caminho, arcname=rel)
        saida = os.path.join(destino, f"ember-{date.today().isoformat()}.tar.gz.cms")
        r = subprocess.run(
            [openssl(), "cms", "-encrypt", "-binary", "-aes-256-cbc", "-in", tar_path, "-out", saida, "-outform", "DER", cert],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not os.path.exists(saida) or os.path.getsize(saida) < 1000:
            print("ERRO no backup:", r.stderr[-300:])
            raise SystemExit(1)
    antigos = sorted(glob.glob(os.path.join(destino, "ember-*.tar.gz.cms")))
    for velho in antigos[:-GUARDAR]:
        os.remove(velho)
    print(f"backup: {os.path.basename(saida)} ({os.path.getsize(saida) // 1024} KB), {min(len(antigos), GUARDAR)} guardados")


if __name__ == "__main__":
    os.umask(0o077)
    main()
