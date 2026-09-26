import base64
import hashlib
import json
import os
import re
import unittest

import _base  # noqa: F401
import painel_montar

TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "painel_template.html")


class Csp(unittest.TestCase):
    def test_hash_do_script_bate_e_sri_presente(self):
        with open(TPL, encoding="utf-8") as f:
            tpl = f.read()
        dados = json.dumps({"x": "</script><script>alert(1)</script>", "y": "__CSP_SCRIPT_HASH__"})
        html = painel_montar.montar(tpl, dados)
        inline = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertEqual(len(inline), 1)
        h = "sha256-" + base64.b64encode(hashlib.sha256(inline[0].encode("utf-8")).digest()).decode()
        meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        self.assertIn(f"'{h}'", meta)
        self.assertNotIn("unsafe-inline' https://cdnjs", meta)
        self.assertNotIn("script-src 'unsafe-inline'", meta)
        self.assertRegex(html, r'chart\.umd\.min\.js" integrity="sha384-[A-Za-z0-9+/=]{64}" crossorigin="anonymous"')
        self.assertEqual(html.index("Content-Security-Policy") < html.index("<script"), True)


if __name__ == "__main__":
    unittest.main()
