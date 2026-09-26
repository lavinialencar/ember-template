"""Test base: synthetic data only, in a temporary folder. Nothing here touches data/ or the network."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import notify  # noqa: E402

TOKEN = "t" * 40
ALERTS = [
    {"key": "suspicious-abc-123", "level": "overdue", "title": "Suspicious purchase on card CARD_X: SHOP_Y",
     "detail": "SHOP_Y", "short": "CARD_X, SHOP_Y (new category).", "action": True},
    {"key": "minimum-banco_a-2026-10-05", "level": "warning", "title": "t", "detail": "d", "short": "CARD_X due Oct 05.", "action": True},
    {"key": "connection-banco_b", "level": "overdue", "title": "Connection stalled: banco_b", "detail": "d", "action": True},
]


class WithTempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "data"))
        with open(os.path.join(self.root, "data", "alerts.json"), "w", encoding="utf-8") as f:
            json.dump({"items": ALERTS}, f)
        self._old_root = notify.ROOT
        notify.ROOT = self.root

    def tearDown(self):
        notify.ROOT = self._old_root
        self.tmp.cleanup()
