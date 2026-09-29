import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import source_handoff as handoff

class SourceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(self.repo)], check=True)
        handoff.git(self.repo, "config", "user.name", "Fixture")
        handoff.git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "third_party").mkdir()
        (self.repo / "third_party/sources.lock.json").write_text('{"sources":{}}')
        (self.repo / ".gitignore").write_text("out/\n.venv/\n")
        self.commit("first")
        handoff.git(self.repo, "tag", "original")
        (self.repo / "module.py").write_text("VALUE = 1\n")
        self.commit("second")
        (self.repo / ".venv").mkdir()
        (self.repo / ".venv/secret").write_text("not source")
        self.destination = self.base / "handoff"

    def commit(self, message):
        handoff.git(self.repo, "add", ".")
        handoff.git(self.repo, "commit", "-q", "-m", message)

    def test_roundtrip_preserves_history_and_tags_without_environment(self):
        report = handoff.create(self.repo, self.destination)
        self.assertEqual(handoff.verify(self.destination)["status"], "PASS")
        clone = self.base / "clone"
        subprocess.run(["git", "clone", "--quiet", str(self.destination / "marsdog-platform.bundle"),
                        str(clone)], check=True)
        self.assertEqual(handoff.git(clone, "rev-parse", "HEAD"), report["source"]["commit"])
        self.assertEqual(handoff.git(clone, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(handoff.git(clone, "tag"), "original")
        self.assertFalse((clone / ".venv").exists())

    def test_dirty_source_and_existing_destination_fail_without_overwrite(self):
        (self.repo / "module.py").write_text("VALUE = 2\n")
        with self.assertRaises(RuntimeError):
            handoff.create(self.repo, self.destination)
        self.assertFalse(self.destination.exists())
        self.commit("changed")
        self.destination.mkdir()
        (self.destination / "keep").write_text("preserve")
        with self.assertRaises(FileExistsError):
            handoff.create(self.repo, self.destination)
        self.assertEqual((self.destination / "keep").read_text(), "preserve")

    def test_tampered_bundle_fails(self):
        handoff.create(self.repo, self.destination)
        with (self.destination / "marsdog-platform.bundle").open("ab") as stream:
            stream.write(b"corruption")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            handoff.verify(self.destination)

    def test_wrong_vendor_is_rejected_before_output_creation(self):
        pins = {"sources": {"vendor": {"archive": "vendor.bundle", "archive_sha256": "0" * 64}}}
        (self.repo / "third_party/sources.lock.json").write_text(json.dumps(pins))
        self.commit("pin vendor")
        archives = self.base / "archives"
        archives.mkdir()
        (archives / "vendor.bundle").write_bytes(b"unexpected")
        with self.assertRaisesRegex(RuntimeError, "changed locked vendor"):
            handoff.create(self.repo, self.destination, archives)
        self.assertFalse(self.destination.exists())

    def test_verify_rejects_manifest_path_escape(self):
        handoff.create(self.repo, self.destination)
        path = self.destination / "manifest.json"
        data = json.loads(path.read_text())
        data["files"]["../escape"] = "0" * 64
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "Unsafe"):
            handoff.verify(self.destination)

if __name__ == "__main__":
    unittest.main()
