import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import dev
import runtime_environment

class DeveloperWorkflowTests(unittest.TestCase):
    def test_setup_has_one_module_and_locked_dependencies(self):
        for name in dev.modules():
            command = dev.setup_command(name, "/tool/uv", "/python")
            self.assertIn("--locked", command)
            self.assertEqual(command.count("--project"), 1)
            self.assertEqual(command[command.index("--project") + 1],
                             str(dev.ROOT / dev.modules()[name]["path"]))
            self.assertNotIn("--all-extras", command)
        self.assertIn("intent-cpu", dev.setup_command("voice", "/uv", "/py", intent_cpu=True))
        with self.assertRaises(ValueError):
            dev.setup_command("action", "/uv", "/py", intent_cpu=True)

    def test_behavior_preserves_both_test_trees(self):
        command, cwd = dev.test_command("behavior", Path("/reports"))
        self.assertIn("tests", command)
        self.assertIn("marsdog_behavior/tests", command)
        self.assertEqual(cwd, dev.ROOT / "modules/behavior")

    def test_voice_pure_and_humble_are_explicit(self):
        pure, _ = dev.test_command("voice", Path("/reports"))
        full, _ = dev.test_command("voice", Path("/reports"), ros=True)
        self.assertEqual(pure[pure.index("--mode") + 1], "pure")
        self.assertEqual(full[full.index("--mode") + 1], "humble")

    def test_failures_empty_suites_and_skips_are_not_full_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "junit.xml"
            path.write_text('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
                            '<testcase name="one"/><testcase name="two"><skipped message="hardware"/></testcase>'
                            '</testsuite></testsuites>')
            report = dev.junit_result(path, 0)
            self.assertEqual(report["status"], "PASS_WITH_EXPLICIT_LIMITS")
            self.assertEqual(report["skips"][0]["reason"], "hardware")
            self.assertEqual(dev.junit_result(path, 1)["status"], "FAIL")
            path.write_text('<testsuite tests="1" skipped="1"/>')
            self.assertEqual(dev.junit_result(path, 0)["status"], "FAIL")
            path.write_text('<testsuite tests="0"/>')
            self.assertEqual(dev.junit_result(path, 0)["status"], "FAIL")

    def test_missing_environment_replaces_stale_pass_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report"
            output.mkdir()
            (output / "result.json").write_text('{"status":"PASS"}')
            with patch.object(dev, "ROOT", root), patch.object(dev, "modules",
                    return_value={"emotion": {"path": "modules/emotion"}}):
                self.assertEqual(dev.test("emotion", output, False), 1)
            self.assertEqual(json.loads((output / "result.json").read_text())["status"], "FAIL")

    def test_archives_never_default_to_sibling_legacy_tree(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_environment.vendor_archive_directory(),
                             runtime_environment.ROOT / ".cache/vendor-archives")
        with patch.dict(os.environ, {"MARSDOG_ARCHIVE_DIR": "/explicit/archive"}):
            self.assertEqual(runtime_environment.vendor_archive_directory(), Path("/explicit/archive"))

    def test_environment_rejects_ambient_module_and_ros_overlays(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/old/repo", "VIRTUAL_ENV": "/other/.venv",
                                    "ROS_DOMAIN_ID": "0", "AMENT_PREFIX_PATH": "/other/install",
                                    "UV_PROJECT_ENVIRONMENT": "/shared/.venv"}):
            env = runtime_environment.clean_environment()
        for key in ("PYTHONPATH", "VIRTUAL_ENV", "ROS_DOMAIN_ID",
                    "AMENT_PREFIX_PATH", "UV_PROJECT_ENVIRONMENT"):
            self.assertNotIn(key, env)

if __name__ == "__main__":
    unittest.main()
