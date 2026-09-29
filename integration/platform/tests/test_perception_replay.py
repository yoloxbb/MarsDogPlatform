"""Asset/provenance/subprocess gate tests; no real inference acceptance."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import check_perception_replay as replay


class ReplayPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.data = {"schema_version": 1, "vision": {
            "model": self.asset("model.onnx"), "samples": [
                {"id": "frame", "image": self.asset("frame.png"), "expected_labels": ["ball"]}]}}

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, name):
        content = ("fixture-" + name).encode()
        (self.root / name).write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}

    def prepare(self):
        self.manifest.write_text(json.dumps(self.data))
        return replay.preflight(self.manifest)


    def test_failed_inference_is_retained_and_other_module_still_runs(self):
        self.data["voice"] = {
            "model": self.asset("asr.onnx"), "tokens": self.asset("tokens.txt"),
            "samples": [{"id": "speech", "audio": self.asset("speech.wav"), "expected_text": "回家"}]}
        self.manifest.write_text(json.dumps(self.data))
        calls = []
        def run(name, request, directory, timeout):
            calls.append(name)
            report = {"status": "PASS", "device": "cpu", "real_model_inference": True,
                      "cases": [{"id": sample["id"], "status": "PASS"} for sample in request["samples"]]}
            if name == "vision":
                report["status"] = "FAIL"
                report["cases"][0]["status"] = "FAIL"
                raise replay.ReplayFailure("Missing expected labels", report)
            return report
        output = self.root / "evidence"
        with mock.patch.object(replay, "run_module", side_effect=run):
            code = replay.main(["--manifest", str(self.manifest), "--output", str(output)])
        result = json.loads(next(output.glob("*/result.json")).read_text())
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["vision", "voice"])
        self.assertTrue(result["inference_executed"])
        self.assertFalse(result["model_acceptance"])
        self.assertEqual(result["modules"]["vision"]["cases"][0]["status"], "FAIL")
        self.assertEqual(result["modules"]["voice"]["status"], "PASS")

    def test_hashes_and_relative_paths(self):
        result = self.prepare()
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["inference_executed"])
        self.assertEqual(result["requests"]["vision"]["model"], str(self.root / "model.onnx"))

    def test_missing_and_tampered_assets_are_distinct(self):
        self.data["vision"]["model"]["path"] = "absent.onnx"
        self.assertEqual(self.prepare()["status"], "BLOCKED_MISSING_ASSETS")
        self.data["vision"]["samples"][0]["image"]["sha256"] = "0" * 64
        self.assertEqual(self.prepare()["status"], "FAIL")

    def test_requires_real_annotations_and_unique_ids(self):
        for samples in ([], [{"id": "x", "image": self.asset("x.png")}],
                        [self.data["vision"]["samples"][0]] * 2):
            with self.subTest(samples=samples):
                self.data["vision"]["samples"] = samples
                with self.assertRaises(ValueError):
                    self.prepare()

    def test_rejects_accelerator_and_mock_settings(self):
        for change in ({"mock_mode": True}, {"device": "cuda"}, {"confidence": float("nan")}):
            self.data["vision"]["settings"] = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare()

    def test_cpu_format_and_sha_required(self):
        self.data["vision"]["model"]["path"] = "model.rknn"
        with self.assertRaises(ValueError):
            self.prepare()
        self.data["vision"]["model"]["path"] = "model.onnx"
        self.data["vision"]["model"]["sha256"] = "unknown"
        with self.assertRaises(ValueError):
            self.prepare()

    def test_negative_image_needs_explicit_annotation(self):
        sample = self.data["vision"]["samples"][0]
        sample.update(expected_empty=True, expected_labels=[])
        self.assertEqual(self.prepare()["status"], "READY")
        sample["expected_labels"] = ["ball"]
        with self.assertRaises(ValueError):
            self.prepare()

    def test_voice_default_catalog_has_recorded_hash(self):
        self.data = {"schema_version": 1, "voice": {
            "model": self.asset("asr.onnx"), "tokens": self.asset("tokens.txt"), "samples": [
                {"id": "command", "audio": self.asset("speech.wav"), "expected_text": "回家"}]}}
        result = self.prepare()
        self.assertEqual(result["status"], "READY")
        self.assertTrue(any(a["name"] == "voice.command_catalog" for a in result["assets"]))

    def test_check_only_and_blocked_never_invoke_module(self):
        self.prepare()
        with mock.patch.object(replay, "run_module", side_effect=AssertionError("unexpected inference")):
            self.assertEqual(replay.main(["--manifest", str(self.manifest), "--check-only",
                                         "--output", str(self.root / "runs")]), 0)
            self.data["vision"]["model"]["path"] = "absent.onnx"
            self.prepare()
            self.assertEqual(replay.main(["--manifest", str(self.manifest),
                                         "--output", str(self.root / "runs")]), 2)
        reports = [json.loads(f.read_text()) for f in (self.root / "runs").glob("*/result.json")]
        self.assertTrue(all(not r["model_acceptance"] for r in reports))

    def test_cli_corrupt_manifest_records_failure(self):
        self.manifest.write_text("not json")
        self.assertEqual(replay.main(["--manifest", str(self.manifest),
                                     "--output", str(self.root / "runs")]), 1)

    def test_changed_asset_during_run_refuses_acceptance(self):
        self.prepare()
        def run(*args):
            (self.root / "model.onnx").write_bytes(b"changed during replay")
            return {"status": "PASS"}
        with mock.patch.object(replay, "run_module", side_effect=run):
            self.assertEqual(replay.main(["--manifest", str(self.manifest),
                                         "--output", str(self.root / "runs")]), 1)

    def test_subprocess_exit_and_missing_sample_cannot_report_pass(self):
        request = self.prepare()["requests"]["vision"]
        for code, cases in [(0, []), (1, [{"id": "frame", "status": "PASS"}])]:
            with self.subTest(code=code):
                directory = self.root / ("run-" + str(code))
                directory.mkdir()
                (directory / "vision.json").write_text(json.dumps({
                    "status": "PASS", "device": "cpu", "real_model_inference": True, "cases": cases}))
                process = mock.Mock(pid=99999)
                process.wait.return_value = code
                with mock.patch.object(replay.subprocess, "Popen", return_value=process):
                    with self.assertRaises(RuntimeError):
                        replay.run_module("vision", request, directory, 2)

    def test_interrupt_reaps_real_worker_and_records_failure(self):
        import os
        import signal
        import subprocess
        import time
        # A real sleeping child verifies ownership cleanup, not model inference.
        self.prepare()
        fake_root = self.root / "fixture-root"
        module = fake_root / "modules/vision"
        executable = module / ".venv/bin/python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(sys.executable)
        worker = module / "blocking_probe.py"
        worker.write_text(
            "import os,time;from pathlib import Path;"
            "Path(__file__).with_suffix('.pid').write_text(str(os.getpid()));"
            "time.sleep(60)")
        marker_path = worker.with_suffix(".pid")
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=sig.name):
                if marker_path.exists():
                    marker_path.unlink()
                output = self.root / sig.name
                code = (
                    "import sys;from pathlib import Path;"
                    f"sys.path.insert(0,{str(ROOT / 'tools')!r});"
                    "import check_perception_replay as r;"
                    f"r.ROOT=Path({str(fake_root)!r});"
                    "r.ENTRYPOINTS['vision']='blocking_probe';"
                    f"raise SystemExit(r.main(['--manifest',{str(self.manifest)!r},'--output',{str(output)!r}]))")
                parent = subprocess.Popen([sys.executable, "-B", "-c", code],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 10
                    while not marker_path.exists() and time.monotonic() < deadline:
                        self.assertIsNone(parent.poll())
                        time.sleep(0.02)
                    self.assertTrue(marker_path.exists(), "Worker did not start")
                    worker_pid = int(marker_path.read_text())
                    parent.send_signal(sig)
                    stdout, stderr = parent.communicate(timeout=10)
                    self.assertEqual(parent.returncode, 1, stdout + stderr)
                    report = json.loads(next(output.glob("*/result.json")).read_text())
                    self.assertEqual(report["status"], "FAIL")
                    self.assertFalse(report["model_acceptance"])
                    self.assertFalse(Path("/proc", str(worker_pid)).exists())
                finally:
                    if parent.poll() is None:
                        parent.kill()
                        parent.wait(timeout=5)
                    if marker_path.exists():
                        try:
                            os.kill(int(marker_path.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_timeout_kills_owned_process_group(self):
        request = self.prepare()["requests"]["vision"]
        process = mock.Mock(pid=99999)
        process.wait.side_effect = [replay.subprocess.TimeoutExpired("inference", 1), 0]
        process.poll.return_value = None
        directory = self.root / "timeout"
        directory.mkdir()
        with mock.patch.object(replay.subprocess, "Popen", return_value=process), mock.patch.object(replay.os, "killpg") as kill:
            with self.assertRaises(replay.subprocess.TimeoutExpired):
                replay.run_module("vision", request, directory, 1)
        kill.assert_called_once_with(99999, replay.signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
