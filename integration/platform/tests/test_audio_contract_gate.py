"""The contract gate must fail closed and never refresh its own oracle."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import check_audio_contracts as gate


class AudioContractGateTests(unittest.TestCase):
    def invoke(self, observed=None, error=None, baseline=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = root / "fixtures"
            output = root / "output"
            fixtures.mkdir()
            output.mkdir()
            expected = {"baseline_commit": "fixture", "observed": {"behavior": {"one": []}}}
            if baseline:
                gate.write_json(fixtures / "baseline.json", expected)
            gate.write_json(output / "result.json", {"status": "PASS"})
            original = (fixtures / "baseline.json").read_bytes() if baseline else None
            with patch.object(gate, "FIXTURES", fixtures), \
                    patch.object(sys, "argv", ["gate", "--output", str(output)]), \
                    patch.object(gate, "observe", return_value=(observed, {}), side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = gate.main()
            report = json.loads((output / "result.json").read_text())
            if baseline:
                self.assertEqual((fixtures / "baseline.json").read_bytes(), original)
            return code, report, (output / "difference.diff").exists()

    def test_mismatch_fails_without_updating_oracle(self):
        code, report, difference = self.invoke(observed={"behavior": {"one": ["unexpected"]}})
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(difference)

    def test_missing_environment_replaces_stale_success(self):
        code, report, _ = self.invoke(error=FileNotFoundError("module python missing"))
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("module python missing", report["error"])

    def test_timeout_replaces_stale_success(self):
        code, report, _ = self.invoke(error=subprocess.TimeoutExpired("worker", 120))
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "FAIL")

    def test_missing_baseline_cannot_pass(self):
        code, report, _ = self.invoke(baseline=False)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "FAIL")

    def test_exact_observation_passes(self):
        code, report, _ = self.invoke(observed={"behavior": {"one": []}})
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["skipped"], 0)

    def test_installed_stale_copy_is_rejected(self):
        source = gate.ROOT / "modules/behavior"
        response = {
            "observed": {},
            "provenance": {
                "stage": "behavior", "prefix": str(source / ".venv"),
                "module_file": str(source / ".venv/lib/python3.10/site-packages/marsdog_behavior/ros_node.py"),
                "foreign_business_modules": [], "ros_importable": False,
            },
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(response), "")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(gate.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
                gate.run_stage("behavior", [], Path(directory))


if __name__ == "__main__":
    unittest.main()
