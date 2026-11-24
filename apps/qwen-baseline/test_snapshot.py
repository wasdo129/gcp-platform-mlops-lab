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

    def test_recovery_and_cache_reuse(self):
        content = b"locked fixture"
        lock = {"repository": "Qwen/model", "revision": "0" * 40, "files": {
            "asset": {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()},
        }}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Unexpected size or type"):
                MODULE.snapshot(lock, root, verify_only=True)
            (root / "asset.part").write_bytes(b"interrupted")
            with patch.object(MODULE, "urlopen", return_value=io.BytesIO(content)) as fetch:
                MODULE.snapshot(lock, root)
                MODULE.snapshot(lock, root)
                self.assertEqual(fetch.call_count, 1)
            (root / "asset").write_bytes(b"x" * len(content))
            with patch.object(MODULE, "urlopen") as fetch:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    MODULE.snapshot(lock, root)
                fetch.assert_not_called()

    def test_rejects_unlocked_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chat_template.jinja").write_text("unlocked override")
            lock = {"repository": "Qwen/model", "revision": "0" * 40, "files": {}}
            with self.assertRaisesRegex(ValueError, "Unexpected snapshot entries"):
                MODULE.snapshot(lock, root, verify_only=True)
