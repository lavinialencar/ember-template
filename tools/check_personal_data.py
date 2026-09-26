#!/usr/bin/env python3
"""Personal data guard: fails if the repository has any identifier of whoever created the template.

Two checks on every text file in the repository (except .git/, data/ and __pycache__/):

1. Denylist by hash. Each word and each pair of words in the text (lowercase, no accents, only [a-z0-9])
   becomes a SHA-256 and is compared with the list below. The list keeps only the hashes: the identifiers themselves
   never show up here. To add a term:  python3 -c "import hashlib;print(hashlib.sha256(b'term').hexdigest())"
2. Shape of personal data:
   - CPF (individual taxpayer ID) with a valid check digit (11 digits, with or without punctuation; a repeated sequence does not count);
   - UUID that does not start with the fake prefix 00000000-0000- (a real Pluggy itemId is a UUID);
   - e-mail outside example.com, example.org and example.net;
   - path of a macOS user folder or of a synced Google Drive folder.

Usage: python3 tools/check_personal_data.py [folder]   (default: the repository root). Exits with 1 if it finds something.
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
SKIP = {".git", "data", "__pycache__", ".venv", "node_modules"}
FAKE_UUID = "00000000-0000-"
EMAIL_OK = ("example.com", "example.org", "example.net")

RE_CPF = re.compile(r"(?<![\d.])(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?![\d.])")
RE_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
RE_PATH = re.compile(r"/Users/[A-Za-z]|Google[D]rive-|Cloud[S]torage/")


def cpf_valid(digits):
    if len(set(digits)) == 1:
        return False
    for n in (9, 10):
        total = sum(int(d) * (n + 1 - i) for i, d in enumerate(digits[:n]))
        if (total * 10 % 11) % 10 != int(digits[n]):
            return False
    return True


def tokens(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", t)
    yield from words
    for a, b in zip(words, words[1:]):
        yield f"{a} {b}"


def check_text(text):
    """List of (line, reason). Never returns the term found, only the reason."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for tk in tokens(line):
            if hashlib.sha256(tk.encode()).hexdigest() in DENYLIST:
                found.append((n, "denylisted identifier"))
                break
        for m in RE_CPF.finditer(line):
            if cpf_valid("".join(m.groups())):
                found.append((n, "CPF with a valid check digit"))
        for m in RE_UUID.finditer(line):
            if not m.group(0).lower().startswith(FAKE_UUID):
                found.append((n, "UUID outside the fake prefix " + FAKE_UUID))
        for m in RE_EMAIL.finditer(line):
            if m.group(1).lower() not in EMAIL_OK:
                found.append((n, "e-mail outside example.com"))
        if RE_PATH.search(line):
            found.append((n, "personal folder path"))
    return found


def files(root):
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [s for s in subfolders if s not in SKIP]
        for name in names:
            yield os.path.join(folder, name)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    total, read = 0, 0
    for path in files(root):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue  # binary
        read += 1
        rel = os.path.relpath(path, root)
        for n, reason in check_text(rel + "\n" + text):
            print(f"{rel}:{n - 1 if n > 1 else 'name'}: {reason}")
            total += 1
    print(f"check_personal_data: {read} files, {total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
