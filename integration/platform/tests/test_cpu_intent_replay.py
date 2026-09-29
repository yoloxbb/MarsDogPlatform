"""Intent orchestration unit fixtures; no model-quality claims."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import check_cpu_intent as replay


class CPUIntentReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        model = self.root / "model"
        model.mkdir()
        weight = model / "model.safetensors"
        weight.write_bytes(b"unit-test-fixture")
        lock = self.root / "lock.json"
        lock.write_text(json.dumps({"files": [{
            "path": weight.name, "size": weight.stat().st_size,
            "sha256": hashlib.sha256(weight.read_bytes()).hexdigest()}]}))
        cases = self.root / "cases.json"
        cases.write_text(json.dumps({"cases": [{
            "id": "fixture", "text": "fixture", "expected_tag": "NONE|NONE|NONE",
            "must_not_execute": True}]}))
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "model_directory": str(model), "model_lock": str(lock),
            "cases": str(cases), "provider": {"type": "qwen_cpu", "enabled": True,
                "config": {"model": str(model)}}}))
        self.voice = self.root / "modules/voice"
        (self.voice / "marsdog_voice_interaction").mkdir(parents=True)
        (self.voice / "pyproject.toml").write_text("# fixture")
        (self.voice / "uv.lock").write_text("# fixture")
        self.patch = mock.patch.object(replay, "ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def run_gate(self):
        return replay.main(["--manifest", str(self.manifest),
                            "--output", str(self.root / "runs"), "--timeout", "1"])

    def report(self):
        return json.loads(next((self.root / "runs").glob("*/result.json")).read_text())

    def worker(self, data, code=0, mutate=None):
        def start(command, **kwargs):
            Path(command[-1]).write_text(json.dumps(data))
            if mutate:
                mutate()
            process = mock.Mock(pid=99999)
            process.wait.return_value = code
            return process
        return start

    def fixture_report(self):
        return {"status": "PASS", "device": "cpu", "real_model_inference": True,
                "torch_cuda_build": None, "cases": [{"id": "fixture", "status": "PASS"}]}

    def test_corrupt_model_never_starts_worker(self):
        (self.root / "model/model.safetensors").write_bytes(b"corrupt")
        with mock.patch.object(replay.subprocess, "Popen") as start:
            self.assertEqual(self.run_gate(), 1)
        start.assert_not_called()
        self.assertFalse(self.report()["model_acceptance"])

    def test_failed_model_report_is_retained(self):
        data = self.fixture_report()
        data.update(status="FAIL", cases=[{"id": "fixture", "status": "FAIL",
                                          "raw_output": "wrong", "errors": ["classification_mismatch"]}])
        with mock.patch.object(replay.subprocess, "Popen", side_effect=self.worker(data, 1)):
            self.assertEqual(self.run_gate(), 1)
        self.assertEqual(self.report()["module"], data)
        self.assertFalse(self.report()["model_acceptance"])

    def test_incomplete_or_non_cpu_report_cannot_pass(self):
        for update in ({"cases": []}, {"real_model_inference": False},
                       {"torch_cuda_build": "13.0"}, {"device": "cuda"}):
            with self.subTest(update=update):
                data = {**self.fixture_report(), **update}
                with mock.patch.object(replay.subprocess, "Popen", side_effect=self.worker(data)):
                    self.assertEqual(self.run_gate(), 1)

    def test_source_drift_refuses_acceptance(self):
        mutate = lambda: (self.voice / "uv.lock").write_text("# changed during inference")
        with mock.patch.object(replay.subprocess, "Popen",
                               side_effect=self.worker(self.fixture_report(), mutate=mutate)):
            self.assertEqual(self.run_gate(), 1)
        self.assertIn("Source or dependency lock changed", self.report()["error"])

    def test_timeout_reaps_only_owned_group(self):
        process = mock.Mock(pid=99999)
        process.poll.return_value = None
        process.wait.side_effect = [replay.subprocess.TimeoutExpired("fixture", 1), 0]
        with mock.patch.object(replay.subprocess, "Popen", return_value=process), mock.patch.object(replay.os, "killpg") as kill:
            self.assertEqual(self.run_gate(), 1)
        kill.assert_called_once_with(99999, replay.signal.SIGKILL)
        self.assertFalse(self.report()["model_acceptance"])


if __name__ == "__main__":
    unittest.main()
