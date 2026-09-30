"""Guard against incomplete acceptance and a stopped child surviving its observer."""
import copy
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from check_business_scenarios import CASE_IDS, evaluate_report
from check_voice_cpu_ros import stop_owned_group


class BusinessScenarioGateTests(unittest.TestCase):
    def fixture(self):
        names = ("voice-1", "vision-1", "voice-2", "vision-2")
        return {
            "status": "PASS", "domain": 216, "real_bt_adapter": True,
            "no_hardware_publishers": True,
            "cases": [{"id": name, "status": "PASS"} for name in CASE_IDS],
            "processes": [{"name": name, "pid": 100 + i, "returncode": 0,
                           "reaped": True, "forced": False} for i, name in enumerate(names)],
            "provenance": {name: {"installed": True} for name in ("behavior", *names)},
        }

    def test_complete_run_is_accepted(self):
        self.assertTrue(evaluate_report(self.fixture(), 0))

    def test_exit_failure_overrides_pass_report(self):
        self.assertFalse(evaluate_report(self.fixture(), 1))

    def test_partial_duplicate_or_failed_case_cannot_pass(self):
        complete = self.fixture()["cases"]
        for cases in ([], complete[:-1], complete + [complete[0]],
                      [complete[0]] * len(complete),
                      [{"id": c["id"], "status": "RUNNING"} for c in complete]):
            with self.subTest(cases=cases):
                self.assertFalse(evaluate_report({**self.fixture(), "cases": cases}, 0))

    def test_domain_adapter_and_hardware_evidence_are_required(self):
        for key, value in (("status", "FAIL"), ("domain", 0),
                           ("real_bt_adapter", False), ("no_hardware_publishers", False)):
            with self.subTest(key=key):
                self.assertFalse(evaluate_report({**self.fixture(), key: value}, 0))

    def test_all_installed_process_generations_are_required(self):
        for name in self.fixture()["provenance"]:
            report = self.fixture()
            del report["provenance"][name]
            self.assertFalse(evaluate_report(report, 0))
        report = self.fixture()
        report["provenance"]["behavior"]["installed"] = False
        self.assertFalse(evaluate_report(report, 0))

    def test_leaked_forced_wrong_or_duplicate_process_cannot_pass(self):
        for changes in ({"pid": -1}, {"pid": True}, {"returncode": -9},
                        {"reaped": False}, {"forced": True}, {"name": "wrong"}):
            report = self.fixture()
            report["processes"][0].update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(evaluate_report(report, 0))
        report = self.fixture()
        report["processes"][1] = copy.deepcopy(report["processes"][0])
        self.assertFalse(evaluate_report(report, 0))
        report["processes"].pop()
        self.assertFalse(evaluate_report(report, 0))

    def test_malformed_observation_is_failure(self):
        for report in (None, [], "PASS", {}, {**self.fixture(), "cases": [None]},
                       {**self.fixture(), "processes": [None]},
                       {**self.fixture(), "processes": None},
                       {**self.fixture(), "provenance": []},
                       {**self.fixture(), "provenance": {"behavior": None}}):
            with self.subTest(report=report):
                self.assertFalse(evaluate_report(report, 0))

    def test_stopped_descendant_is_terminated_after_observer_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child.pid"
            code = ("import subprocess,sys;from pathlib import Path;"
                    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
                    f"Path({str(marker)!r}).write_text(str(p.pid))")
            parent = subprocess.Popen([sys.executable, "-B", "-c", code],
                                      start_new_session=True, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            child_pid = None
            try:
                parent.wait(timeout=10)
                child_pid = int(marker.read_text())
                os.kill(child_pid, signal.SIGSTOP)
                status = Path("/proc", str(child_pid), "status")
                deadline = time.monotonic() + 2
                while "State:\tT" not in status.read_text():
                    self.assertLess(time.monotonic(), deadline, "child was not stopped")
                    time.sleep(0.01)
                stop_owned_group(parent)
                deadline = time.monotonic() + 2
                while status.exists() and "State:\tZ" not in status.read_text():
                    self.assertLess(time.monotonic(), deadline, "stopped child survived cleanup")
                    time.sleep(0.01)
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
