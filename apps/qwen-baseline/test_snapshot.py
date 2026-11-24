import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FILES = ROOT / "gitops/charts/qwen-serving/files"
SPEC = importlib.util.spec_from_file_location("model_snapshot", FILES / "model_snapshot.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SnapshotTests(unittest.TestCase):
    def test_model_lock_is_complete(self):
        lock = json.loads((FILES / "model-lock.json").read_text())
        self.assertEqual(lock["revision"], "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e")
        self.assertEqual(sum(file["size"] for file in lock["files"].values()), 4079434577)
        for file in lock["files"].values():
            self.assertRegex(file["sha256"], r"^[a-f0-9]{64}$")

    def test_verified_download_and_mismatch(self):
        content = b"small fixture"
        entry = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset"
            with patch.object(MODULE, "urlopen", return_value=io.BytesIO(b"x" * len(content))):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    MODULE.download("https://example.invalid", path, entry)
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch.object(MODULE, "urlopen", return_value=io.BytesIO(content)):
                MODULE.download("https://example.invalid", path, entry)
            MODULE.verify(path, entry)
            self.assertEqual(path.read_bytes(), content)

    def test_rejects_file_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = {"repository": "Qwen/model", "revision": "0" * 40, "files": {"../outside": {}}}
            with self.assertRaisesRegex(ValueError, "Invalid filename"):
                MODULE.snapshot(lock, Path(directory), verify_only=True)
