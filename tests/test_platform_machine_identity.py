import json
import tempfile
import unittest
from pathlib import Path

from rpa_platform.worker.machine_identity import load_or_create_machine_id


class MachineIdentityTest(unittest.TestCase):
    def test_creates_and_reuses_machine_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "machine.json"

            first = load_or_create_machine_id(path)
            second = load_or_create_machine_id(path)

            self.assertEqual(first, second)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["machine_id"], first)
            self.assertTrue(first.startswith("mch_"))
