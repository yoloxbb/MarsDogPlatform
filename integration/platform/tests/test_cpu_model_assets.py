"""Real filesystem checks for model integrity and extraction boundaries."""
import hashlib
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_cpu_models as models

class AssetIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.body = b"cpu-model-test-bytes"
        self.spec = {"size": len(self.body), "sha256": hashlib.sha256(self.body).hexdigest()}

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_verified_bytes_and_reuse_without_fetch(self):
        path = self.root / "weights/model.pt"
        models.materialize(path, self.spec, lambda: io.BytesIO(self.body))
        models.materialize(path, self.spec, lambda: self.fail("Cached model refetched"))
        self.assertEqual(path.read_bytes(), self.body)

    def test_bad_hash_and_size_never_publish(self):
        for spec in (dict(self.spec, sha256="0"*64), dict(self.spec, size=2)):
            with self.assertRaises(ValueError):
                models.materialize(self.root / "model.pt", spec, lambda: io.BytesIO(self.body))
            self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_corrupt_file_is_preserved_and_rejected(self):
        path = self.root / "model.pt"
        path.write_bytes(b"user-content")
        with self.assertRaises(ValueError):
            models.materialize(path, self.spec, lambda: io.BytesIO(self.body))
        self.assertEqual(path.read_bytes(), b"user-content")

    def test_interrupted_source_does_not_publish_or_leave_temporary_file(self):
        def source():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            models.materialize(self.root / "model.pt", self.spec, source)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_traversal_absolute_windows_and_symlink_escape_rejected(self):
        for name in ("../x", "/tmp/x", "a/../../x", "a\\x", "C:x", ".", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                models.safe_path(self.root, name)
        (self.root / "outside").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            models.safe_path(self.root, "outside/escaped")

    def test_zip_traversal_and_symlinks_rejected_before_extraction(self):
        for info in (zipfile.ZipInfo("../escape"), zipfile.ZipInfo("symlink")):
            if info.filename == "symlink":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(info, b"outside")
            with zipfile.ZipFile(buffer) as archive, self.assertRaises(ValueError):
                models.checked_zip(archive)

    def test_zip_duplicate_names_rejected(self):
        import warnings
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive, warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("same", b"a")
            archive.writestr("same", b"b")
        with zipfile.ZipFile(buffer) as archive, self.assertRaises(ValueError):
            models.checked_zip(archive)

if __name__ == "__main__":
    unittest.main()
