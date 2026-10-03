"""Negative acceptance tests: a PASS label alone is never evidence."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from trial_report import evaluate_trial, write_trial_report
from recording_trial import validate_wav
from new_feature import create, validate_proposal, REQUIRED_CASES
from check_decision_scenarios import CASE_IDS, evaluate_report
from capabilities import combine


class RecordingTrialTests(unittest.TestCase):
    def fixture(self):
        identity = {"interaction_id": "session", "utterance_id": "turn"}
        return {
            **identity, "status": "PASS", "observer_pid": 100, "worker_returncode": 0,
            "real_asr_cases": 1, "text_fixture_cases": 0, "no_hardware_publishers": True,
            "worker": {"pid": 101, "status": "PASS", "asr": [{
                "kind": "real_sensevoice_cpu", "result": {"reason": "ok", "asr_text": "回家"}}]},
            "command_goals": [{"goal_id": "goal", "params": identity}],
            "command_terminals": [{"goal_id": "goal", "status": "SUCCESS"}],
            "command_events": [{**identity, "should_trigger_behavior_tree": True}],
            "outcome": "success", "expectation_errors": [],
        }

    def test_complete_trial_and_failed_expectation_are_separate(self):
        value = self.fixture()
        self.assertEqual(evaluate_trial(value, 0), (True, True))
        value["expectation_errors"] = ["wrong_event"]
        self.assertEqual(evaluate_trial(value, 0), (True, False))
        self.assertEqual(evaluate_trial(value, 1), (False, False))

    def test_incomplete_or_forged_success_fails(self):
        for changes in (
            {"observer_pid": 0}, {"observer_pid": True}, {"observer_pid": 101},
            {"worker_returncode": -9}, {"no_hardware_publishers": False},
            {"text_fixture_cases": 1}, {"real_asr_cases": 0}, {"command_goals": []},
            {"command_events": []}, {"command_terminals": []}, {"status": "RUNNING"},
            {"outcome": "rejected_before_goal"}, {"outcome": "no_dispatch_requested"},
            {"command_terminals": [{"goal_id": "goal", "status": "FAILURE"}]},
            {"command_terminals": [{"goal_id": "other", "status": "SUCCESS"}]},
            {"command_goals": [{"goal_id": None, "params": {}}]},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(evaluate_trial({**self.fixture(), **changes}, 0), (False, False))

    def test_wrong_turn_duplicate_terminal_and_fake_asr_fail(self):
        value = self.fixture()
        value["command_goals"][0]["params"] = {"interaction_id": "other", "utterance_id": "turn"}
        self.assertFalse(evaluate_trial(value, 0)[0])
        value = self.fixture()
        value["command_terminals"] *= 2
        self.assertFalse(evaluate_trial(value, 0)[0])
        for update in ({"kind": "explicit_text_fixture_no_asr"}, {"result": {"reason": "ok", "asr_text": ""}},
                       {"result": {"reason": "error", "asr_text": "回家"}}):
            value = self.fixture()
            value["worker"]["asr"][0].update(update)
            self.assertFalse(evaluate_trial(value, 0)[0])

    def test_observed_gating_is_valid_but_not_success(self):
        value = self.fixture()
        value["command_terminals"][0]["status"] = "FAILURE"
        value["outcome"] = "action_failed_or_canceled"
        self.assertEqual(evaluate_trial(value, 0), (True, True))
        value["command_terminals"][0]["status"] = "RUNNING"
        self.assertFalse(evaluate_trial(value, 0)[0])

    def test_no_goal_requires_matching_rejection_or_no_execution_request(self):
        value = self.fixture()
        value.update(command_goals=[], command_terminals=[], outcome="rejected_before_goal")
        self.assertFalse(evaluate_trial(value, 0)[0])
        value["rejections"] = [{"interaction_id": "session", "utterance_id": "turn",
                                "stage": "candidate_rejected", "reason": "need_gate"}]
        self.assertTrue(evaluate_trial(value, 0)[0])
        value["rejections"][0]["utterance_id"] = "other"
        self.assertFalse(evaluate_trial(value, 0)[0])
        value["outcome"] = "no_dispatch_requested"
        value["command_events"][0]["should_trigger_behavior_tree"] = False
        self.assertTrue(evaluate_trial(value, 0)[0])

    def test_malformed_evidence_fails_without_crashing(self):
        for value in (None, [], {}, {"worker": None}, {**self.fixture(), "command_goals": [None]}):
            self.assertEqual(evaluate_trial(value, 0), (False, False))

    def test_wav_validation_rejects_format_and_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.wav"
            for rate, channels, width, frames, valid in (
                (16000, 1, 2, 1600, True), (44100, 1, 2, 1600, False),
                (16000, 2, 2, 1600, False), (16000, 1, 1, 1600, False),
                (16000, 1, 2, 0, False)):
                with wave.open(str(path), "wb") as stream:
                    stream.setparams((channels, width, rate, 0, "NONE", "not compressed"))
                    stream.writeframes(b"\0" * channels * width * frames)
                if valid:
                    self.assertEqual(validate_wav(path), path)
                    original = path.read_bytes()
                    path.write_bytes(original[:-10])
                    with self.assertRaises(ValueError):
                        validate_wav(path)
                else:
                    with self.assertRaises(ValueError):
                        validate_wav(path)

    def test_html_escapes_data_and_keeps_unrelated_turn_out_of_trace(self):
        value = self.fixture()
        value["worker"]["asr"][0]["result"]["asr_text"] = "<script>alert(1)</script>"
        value["worker"]["asr"][0].update(started_monotonic_ns=10, finished_monotonic_ns=20, elapsed_ms=0.01)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "structured").mkdir()
            rows = [
                {"interaction_id": "session", "utterance_id": "turn", "goal_id": "goal", "stage": "goal_dispatch", "monotonic_ns": 30},
                {"goal_id": "goal", "stage": "action_terminal", "monotonic_ns": 40},
                {"interaction_id": "other", "utterance_id": "other", "goal_id": "unrelated", "stage": "goal_dispatch", "monotonic_ns": 35},
            ]
            records = [{"log_schema_version": 2, "timestamp": "2026-10-04T00:00:00Z",
                        "component": "behavior", "instance_id": "one", "sequence": index,
                        "level": "INFO", "kind": "lifecycle", "fields": {},
                        "event_name": "behavior." + row["stage"].replace("_", "."),
                        "monotonic_ns": row["monotonic_ns"],
                        "context": {key: value for key, value in row.items() if key.endswith("_id")}}
                       for index, row in enumerate(rows)]
            (directory / "structured/behavior-1.jsonl").write_text("\n".join(json.dumps(r) for r in records))
            report = {"status": "PASS", "probe": value}
            write_trial_report(directory, report)
            trace = json.loads((directory / "trace.json").read_text())
            self.assertEqual([r["stage"] for r in trace], ["asr_started", "asr_completed", "goal_dispatch", "action_terminal"])
            self.assertNotIn("<script>", (directory / "report.html").read_text())
            self.assertIn("&lt;script&gt;", (directory / "report.html").read_text())


class DecisionGateTests(unittest.TestCase):
    def fixture(self):
        return {"status": "PASS", "domain": 217, "no_hardware_publishers": True,
                "cases": [{"id": name, "status": "PASS"} for name in CASE_IDS],
                "processes": [{"name": name, "pid": i + 100, "returncode": 0, "reaped": True, "forced": False}
                              for i, name in enumerate(("inputs", "waypoint", "action", "behavior"))],
                "provenance": {"action": {"installed": True}, "behavior": {"installed": True}}}

    def test_complete_run(self):
        self.assertTrue(evaluate_report(self.fixture(), 0))
        self.assertFalse(evaluate_report(self.fixture(), 1))

    def test_incomplete_cases_leaks_hardware_and_source_imports_fail(self):
        for field, value in (("cases", []), ("domain", 0), ("no_hardware_publishers", False),
                             ("provenance", {}), ("processes", None)):
            self.assertFalse(evaluate_report({**self.fixture(), field: value}, 0))
        for change in ({"pid": True}, {"pid": -1}, {"returncode": -9}, {"reaped": False}, {"forced": True}):
            value = self.fixture()
            value["processes"][0].update(change)
            self.assertFalse(evaluate_report(value, 0))
        value = self.fixture()
        value["cases"][1] = value["cases"][0]
        self.assertFalse(evaluate_report(value, 0))


class FeatureDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "interfaces/naming/catalog.json").read_text())

    def proposal(self):
        return {"schema_version": 1, "name": "welcome_demo", "phrase": "测试欢迎",
                "event": "EVT_VOICE_COMMAND_WELCOME_DEMO", "command_id": "CMD_WELCOME_DEMO",
                "intent": "command_welcome_demo", "behavior": "sit_down"}

    def test_draft_does_not_activate_or_overwrite_and_tests_are_real(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "draft"
            create(self.proposal(), destination, self.catalog)
            self.assertEqual(validate_proposal(json.loads((destination / "feature.json").read_text()), self.catalog), [])
            cases = json.loads((destination / "acceptance.json").read_text())
            self.assertEqual(cases["status"], "NOT_RUN")
            self.assertEqual([c["id"] for c in cases["cases"]], list(REQUIRED_CASES))
            for filename in ("test_voice_contract.py", "test_behavior_contract.py", "test_action_contract.py"):
                tree = ast.parse((destination / filename).read_text())
                self.assertTrue(any(isinstance(n, ast.Assert) for n in ast.walk(tree)))
            with self.assertRaises(FileExistsError):
                create(self.proposal(), destination, self.catalog)

    def test_collisions_and_unknown_capabilities_are_rejected_before_writing(self):
        for change in ({"name": "../escape"}, {"event": "bad"}, {"phrase": ""},
                       {"behavior": "not_implemented"}, {"event": "EVT_VOICE_COMMAND_SIT"},
                       {"command_id": "CMD_SIT"}, {"intent": "command_sit"},
                       {"phrase": None}, {"behavior": []}, {"event": {}}, {"schema_version": True}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "draft"
                with self.assertRaises(ValueError):
                    create({**self.proposal(), **change}, destination, self.catalog)
                self.assertFalse(destination.exists())
        self.assertTrue(validate_proposal(None, self.catalog))

    def test_custom_event_keeps_product_label_consistent(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "draft"
            create({**self.proposal(), "event": "EVT_VOICE_COMMAND_CUSTOM_DEMO"}, destination, self.catalog)
            fragments = json.loads((destination / "config_fragments.json").read_text())
            self.assertEqual(fragments["voice_command"]["action_name"], "ACT_CUSTOM_DEMO")

    def test_capability_routes_do_not_promote_missing_or_blocked_templates(self):
        catalog = {"routes": [
            {"executor_behaviors": ["missing"]}, {"executor_behaviors": ["blocked"]},
            {"executor_behaviors": ["ready"]}], "source_sha256": {}, "voice_commands": [], "social_reactions": []}
        action = {"behaviors": {"blocked": {"configuration_status": "blocked"},
                                "ready": {"configuration_status": "runtime_check_required"}}}
        report = combine(catalog, action)
        self.assertEqual([r["configuration_status"] for r in report["routes"]],
                         ["missing_template", "blocked", "runtime_check_required"])
        self.assertEqual(report["hardware_acceptance"], "unknown")
