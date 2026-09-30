"""Failure injection for frozen contract gates and architectural dependency rules."""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import contract_harness as gate
from component_inventory import COMPONENTS


class ContractHarnessTests(unittest.TestCase):
    def invoke(self, observed=None, error=None, baseline="valid"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures, output = root / "fixtures", root / "output"
            fixtures.mkdir()
            output.mkdir()
            expected = {"baseline_commit": "fixture", "observed": {"behavior": {"one": []}}}
            if baseline == "empty":
                expected["observed"]["behavior"] = {}
            if baseline != "missing":
                gate.write_json(fixtures / "baseline.json", expected)
            original = (fixtures / "baseline.json").read_bytes() if baseline != "missing" else None
            gate.write_json(output / "result.json", {"status": "PASS"})
            def observe(_):
                if error:
                    raise error
                return observed, {}
            with patch.object(sys, "argv", ["gate", "--output", str(output)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = gate.check_main(fixtures, observe, output)
            report = json.loads((output / "result.json").read_text())
            if original is not None:
                self.assertEqual((fixtures / "baseline.json").read_bytes(), original)
            return code, report, (output / "difference.diff").exists()

    def test_mismatch_preserves_oracle_and_fails(self):
        code, report, diff = self.invoke({"behavior": {"one": ["wrong"]}})
        self.assertEqual((code, report["status"], diff), (1, "FAIL", True))

    def test_missing_baseline_replaces_stale_success(self):
        self.assertEqual(self.invoke(baseline="missing")[1]["status"], "FAIL")

    def test_empty_baseline_cannot_certify_zero_work(self):
        self.assertEqual(self.invoke({"behavior": {}}, baseline="empty")[1]["status"], "FAIL")

    def test_missing_environment_replaces_stale_success(self):
        self.assertEqual(self.invoke(error=FileNotFoundError("python"))[1]["status"], "FAIL")

    def test_timeout_replaces_stale_success(self):
        self.assertEqual(self.invoke(error=subprocess.TimeoutExpired("worker", 120))[1]["status"], "FAIL")

    def test_bad_worker_response_replaces_stale_success(self):
        self.assertEqual(self.invoke({"unrelated": None})[1]["status"], "FAIL")

    def test_exact_observation_has_no_skips(self):
        code, report, _ = self.invoke({"behavior": {"one": []}})
        self.assertEqual((code, report["status"], report["skipped"]), (0, "PASS", 0))
        self.assertEqual(report["stage_observations"], {"behavior": 1})

    def stage(self, patch_values=None, *, ros=False, returncode=0):
        source = gate.ROOT / "modules/behavior"
        origin = {"stage": "behavior", "prefix": str(source / ".venv"),
                  "module_file": str(source / "marsdog_behavior/ros_node.py"),
                  "foreign_business_modules": [], "ros_importable": ros}
        origin.update(patch_values or {})
        completed = subprocess.CompletedProcess([], returncode, json.dumps({"provenance": origin}), "")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(gate.subprocess, "run", return_value=completed), \
                patch.object(gate, "ros_environment", return_value={}):
            return gate.run_stage("behavior", [], Path(directory), ROOT / "integration/contracts/state_stage.py", ros=ros)

    def test_stale_wheel_rejected(self):
        source = gate.ROOT / "modules/behavior"
        with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
            self.stage({"module_file": str(source / ".venv/lib/python3.10/site-packages/marsdog_behavior/ros_node.py")})

    def test_foreign_environment_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
            self.stage({"prefix": "/foreign/.venv"})

    def test_foreign_business_import_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
            self.stage({"foreign_business_modules": ["marsdog_core"]})

    def test_ros_contamination_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
            self.stage({"ros_importable": True})

    def test_missing_ros_in_service_gate_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid module provenance"):
            self.stage({"ros_importable": False}, ros=True)

    def test_worker_failure_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "behavior failed"):
            self.stage(returncode=1)


class ComponentBoundaryTests(unittest.TestCase):
    def test_components_do_not_depend_on_ros_shell_or_foreign_business(self):
        families = {
            "voice": {"marsdog_voice_interaction"}, "vision": {"marsdog_vision_interaction"},
            "emotion": {"marsdog_core", "marsdog_ros2"},
            "behavior": {"marsdog_behavior", "bionic_dog_bt"},
            "action": {"marsdog_action_executor"},
        }
        for stage, names in COMPONENTS.items():
            forbidden = set.union(*(v for k, v in families.items() if k != stage))
            for name in names:
                with self.subTest(component=name):
                    source = ROOT / "modules" / stage / (name.replace(".", "/") + ".py")
                    tree = ast.parse(source.read_text())
                    for node in ast.walk(tree):
                        imports = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                                   else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                        for imported in imports:
                            parts = imported.split(".")
                            self.assertNotIn(parts[0], forbidden | {"rclpy", "std_msgs"})
                            self.assertNotIn("ros_node", parts)
                            self.assertNotIn("nodes", parts)


if __name__ == "__main__":
    unittest.main()
