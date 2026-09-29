"""Acceptance tests for the CPU ROS orchestrator; all reports here are fixtures."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from check_voice_cpu_ros import evaluate_report, stop_owned_group


class CPUROSReportTests(unittest.TestCase):
    def fixture(self):
        return {"integration_acceptance": True, "worker_returncode": 0,
                "real_asr_cases": 1, "text_fixture_cases": 4, "after_stop_no_inference": True,
                "observer_pid": 100, "worker": {"pid": 101}, "cases": [
                    {"id": x, "transport_errors": [], "quality_errors": []}
                    for x in ("upstream-zh-itn", "qwen-sit", "qwen-no-sit", "qwen-reject", "catalog-sit")]}

    def test_quality_failure_remains_distinct_from_real_transport(self):
        report = self.fixture()
        report["cases"][0]["quality_errors"] = ["intent_tag_mismatch"]
        self.assertEqual(evaluate_report(report, 0), (True, False))

    def test_mock_or_incomplete_evidence_cannot_pass(self):
        for changes in ({"real_asr_cases": 0}, {"worker": {"pid": 100}},
                        {"worker": {}}, {"cases": []}, {"worker_returncode": 1}, {"text_fixture_cases": 5}):
            with self.subTest(changes=changes):
                self.assertEqual(evaluate_report({**self.fixture(), **changes}, 0), (False, False))
        self.assertEqual(evaluate_report(self.fixture(), 1), (False, False))

    def test_execution_violation_fails_both_gates(self):
        report = self.fixture()
        report["cases"][2]["transport_errors"] = ["Unexpected executable event"]
        self.assertEqual(evaluate_report(report, 0), (False, False))


    def test_failed_observer_does_not_leave_a_real_descendant_running(self):
        import os
        import signal
        import subprocess
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child.pid"
            code = (
                "import subprocess,sys;from pathlib import Path;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
                f"Path({str(marker)!r}).write_text(str(p.pid))")
            parent = subprocess.Popen([sys.executable, "-B", "-c", code],
                                      start_new_session=True,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child_pid = None
            try:
                parent.wait(timeout=10)
                child_pid = int(marker.read_text())
                stop_owned_group(parent)
                status = Path("/proc", str(child_pid), "status")
                self.assertTrue(not status.exists() or "State:\tZ" in status.read_text())
            finally:
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
