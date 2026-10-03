"""Run ownership, query correlation and retention must not damage task assets."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from log_query import read_records, select_records, query_records
from log_runs import prepare_logging, finish_logging, retention_plan, apply_retention


class UnifiedLogToolsTests(unittest.TestCase):
    def row(self, component, **extra):
        return {"log_schema_version": 1, "timestamp": "2026-10-04T00:00:00+00:00",
                "component": component, "instance_id": component, "sequence": 1,
                "level": "INFO", "event_name": "test", "fields": {}, **extra}

    def test_session_query_links_goal_only_terminal_without_matching_other_turn(self):
        rows = [self.row("voice", interaction_id="one", utterance_id="u"),
                self.row("behavior", interaction_id="one", utterance_id="u", goal_id="g"),
                self.row("action", goal_id="g"),
                self.row("action", goal_id="other"),
                self.row("voice", interaction_id="two", utterance_id="u")]
        selected = select_records(rows, interaction="one", utterance="u")
        self.assertEqual([r["component"] for r in selected], ["voice", "behavior", "action"])
        self.assertEqual(select_records(rows, goal="g"), rows[1:3])

    def test_component_severity_and_event_filters_include_native_ros_origin(self):
        rows = [self.row("ros", level="WARNING", event_name="ros.message", fields={"source_component": "emotion"}),
                self.row("emotion", level="DEBUG"), self.row("action", level="ERROR")]
        self.assertEqual(select_records(rows, component="emotion", level="warning", event="ros."), rows[:1])

    def test_reader_keeps_valid_rows_and_reports_partial_or_wrong_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "structured").mkdir()
            (directory / "structured/test.jsonl").write_text(json.dumps(self.row("voice")) + '\n{"broken"\n[]\n')
            rows, errors = read_records(directory)
            self.assertEqual(len(rows), 1)
            self.assertEqual([e["line"] for e in errors], [2, 3])

    def test_reader_rejects_wrong_field_types_and_query_limits_after_filtering(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "structured"
            path.mkdir()
            rows = [self.row("action", sequence=n, goal_id="match" if n % 2 else "other")
                    for n in range(1, 10)]
            rows += [self.row("action", fields=None), self.row("action", sequence="wrong")]
            (path / "test.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            selected, errors = query_records(temp, limit=2, goal="match")
            self.assertEqual([r["sequence"] for r in selected], [7, 9])
            self.assertEqual(len(errors), 2)

    def test_identity_types_and_explicit_other_session_are_not_joined(self):
        rows = [self.row("voice", interaction_id="one", candidate_id="g", goal_id="actual"),
                self.row("action", goal_id="g"),
                self.row("action", goal_id="actual", interaction_id="two"),
                self.row("action", goal_id="actual")]
        self.assertEqual(select_records(rows, interaction="one"), [rows[0], rows[3]])

    def test_run_identity_shared_and_close_marks_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            env, path = {}, Path(temp)
            one = prepare_logging(env, path)
            self.assertEqual(env["MARSDOG_RUN_ID"], one["run_id"])
            self.assertEqual(one["state"], "active")
            finish_logging(path, "FAIL")
            final = json.loads((path / "log-manifest.json").read_text())
            self.assertEqual(final["run_id"], one["run_id"])
            self.assertEqual((final["state"], final["outcome"]), ("closed", "FAIL"))

    def test_prune_only_closed_managed_logs_preserves_audio_config_and_active_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("active", "closed"):
                run = root / name
                prepare_logging({}, run)
                (run / "structured").mkdir()
                (run / "structured/worker.jsonl").write_text("evidence")
                (run / "worker.log").write_text("raw")
                (run / "input.wav").write_bytes(b"preserve")
                (run / "config.yaml").write_text("preserve")
                (run / "result.json").write_text("{}")
            finish_logging(root / "closed", "PASS")
            legacy = root / "unmanaged"
            legacy.mkdir()
            (legacy / "old.log").write_text("preserve")
            plan = retention_plan(root, keep_runs=0)
            self.assertEqual(len(plan["files"]), 2)
            self.assertTrue((root / "closed/worker.log").exists())  # dry-run
            apply_retention(plan, root)
            self.assertFalse((root / "closed/worker.log").exists())
            for name in ("active", "closed"):
                self.assertTrue((root / name / "input.wav").exists())
                self.assertTrue((root / name / "config.yaml").exists())
                self.assertTrue((root / name / "result.json").exists())
            self.assertTrue((root / "active/worker.log").exists())
            self.assertTrue((legacy / "old.log").exists())

    def test_symlink_escape_and_newly_active_run_cannot_be_pruned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.log").write_text("preserve")
            run = root / "runs/one"
            prepare_logging({}, run)
            (run / "structured").symlink_to(outside, target_is_directory=True)
            (run / "normal.log").write_text("temporary")
            finish_logging(run, "PASS")
            plan = retention_plan(root / "runs", keep_runs=0)
            self.assertEqual(len(plan["files"]), 1)
            self.assertNotIn("secret", str(plan))
            prepare_logging({}, run)
            with self.assertRaises(ValueError):
                apply_retention(plan, root / "runs")
            self.assertTrue((outside / "secret.log").exists())

    def test_active_logs_over_budget_are_reported_and_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "active"
            prepare_logging({}, run)
            (run / "worker.log").write_bytes(b"x" * 64)
            plan = retention_plan(root, keep_runs=0, max_total_bytes=16)
            self.assertTrue(plan["active_budget_exceeded"])
            self.assertEqual(plan["files"], [])
