"""Configuration drift and false acceptance must fail before producing a release view."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import capabilities
import capability_snapshot as snapshot
import event_inventory as inventory
from check_identifiers import CATALOG, EXCEPTIONS, validate


class EventInventoryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / CATALOG).read_text(encoding="utf-8"))
        self.exceptions = json.loads((ROOT / EXCEPTIONS).read_text(encoding="utf-8"))

    def test_real_tactile_and_emotion_routes_are_distinct(self):
        index = {r["event"]: r for r in self.catalog["event_index"]}
        self.assertEqual(index["EVT_TACTILE_HEAD_PET"]["classification"], "direct_and_emotion")
        self.assertEqual(index["EVT_TACTILE_BODY_STROKE"]["classification"], "emotion_only")
        self.assertEqual(index["EVT_VOICE_COMFORT"]["classification"], "emotion_only")
        self.assertEqual(index["EVT_VISION_FALL"]["classification"], "direct_and_emotion")
        self.assertEqual(index["EMO_JOY_TRIGGERED"]["classification"], "internal_trigger")

    def test_social_expression_style_does_not_change_behavior_origin(self):
        rows = self.catalog["reaction_routes"]
        self.assertTrue(rows)
        self.assertTrue(all(r["source"] == "audio_reaction" for r in rows))
        ids = {inventory.route_id(r) for r in rows}
        indexed = {p for r in self.catalog["event_index"] for p in r["direct_paths"]}
        self.assertTrue(ids <= indexed)

    def test_missing_tactile_template_cannot_reuse_a_legacy_exception(self):
        self.catalog["tactile_routes"][0]["executor_behaviors"] = ["not_implemented"]
        report = validate(self.catalog, self.exceptions)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("missing supplemental template" in e for e in report["errors"]))

    def test_bad_subranks_and_nonpositive_cooldowns_are_rejected(self):
        for field, value in (("sub_priority", 2.1), ("sub_priority", True),
                             ("priority_level", 0), ("cooldown_sec", 0), ("ttl_sec", float("nan"))):
            with self.subTest(field=field, value=value):
                broken = deepcopy(self.catalog)
                broken["tactile_routes"][0]["configured_policy"][field] = value
                self.assertTrue(inventory.analyze(broken))

    def test_emotion_typo_is_an_error_not_a_new_emotion(self):
        self.catalog["emotion_effects"]["EVT_TACTILE_HEAD_PET"]["deltas"]["Jyo"] = 10
        self.assertTrue(any("invalid emotion delta" in e for e in inventory.analyze(self.catalog)))

    def test_legacy_nested_rank_cannot_bypass_integer_validation(self):
        row = next(iter(self.catalog["route_policies"].values()))
        row["params"] = {"behavior_rank": 2.1}
        self.assertTrue(any("invalid integer rank" in e for e in inventory.analyze(self.catalog)))

    def test_index_cannot_silently_drop_the_emotional_half(self):
        next(r for r in self.catalog["event_index"] if r["event"] == "EVT_TACTILE_HEAD_PET")["emotion_rule"] = None
        self.assertIn("event index differs from owning rules", inventory.analyze(self.catalog))

    def test_missing_policy_and_duplicate_routes_are_detected(self):
        self.catalog["route_policies"].pop(next(iter(self.catalog["route_policies"])))
        self.catalog["tactile_routes"].append(deepcopy(self.catalog["tactile_routes"][0]))
        errors = inventory.analyze(self.catalog)
        self.assertTrue(any("policy coverage" in e for e in errors))
        self.assertTrue(any("duplicate supplemental" in e for e in errors))

    def test_runtime_entry_template_and_symbol_are_checked(self):
        self.catalog["code_entrypoints"][0]["executor_behaviors"] = ["absent"]
        self.assertTrue(any("runtime entry template" in e for e in inventory.analyze(self.catalog)))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "example.py").write_text("class Coordinator:\n    def run(self): pass\n")
            self.assertTrue(inventory.symbol_exists(root, "example.py", "Coordinator.run"))
            self.assertFalse(inventory.symbol_exists(root, "example.py", "Coordinator.removed"))

    def test_default_catalog_keeps_original_missing_template_exceptions_exact(self):
        original = deepcopy(self.exceptions)
        result = validate(self.catalog, self.exceptions)
        self.assertEqual(result["status"], "PASS_WITH_KNOWN_GAPS")
        self.assertEqual(result["counts"]["known_missing_template_routes"], 16)
        self.assertEqual(self.exceptions, original)

    def test_disabled_tactile_is_listed_but_never_promoted_to_ready(self):
        row = deepcopy(self.catalog["tactile_routes"][0]); row["enabled"] = False
        action = {"behaviors": {row["executor_behaviors"][0]: {"configuration_status": "runtime_check_required"}}}
        result = snapshot.describe_route(row, action)
        self.assertEqual(result["configuration_status"], "blocked")
        self.assertEqual(set(result["acceptance"].values()), {"NOT_RECORDED"})


class SnapshotEvidenceTests(unittest.TestCase):
    def test_pass_report_reference_does_not_claim_capability_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); report = root / "result.json"
            report.write_text(json.dumps({"status": "PASS", "scope": "pure software"}))
            refs = snapshot.evidence_references([report], root)
            self.assertEqual(refs[0]["reported_status"], "PASS")
            self.assertEqual(refs[0]["binding"], "reference_only_not_capability_acceptance")
            self.assertEqual(refs[0]["sha256"], snapshot.sha256(report))

    def test_failed_report_is_preserved_as_failed_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); report = root / "result.json"
            report.write_text('{"status":"FAIL"}')
            self.assertEqual(snapshot.evidence_references([report], root)[0]["reported_status"], "FAIL")

    def test_malformed_and_duplicate_reports_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); report = root / "result.json"
            for data in ({"counts": {"passed": 100}}, {"status": True}, {"status": ["PASS"]}, []):
                report.write_text(json.dumps(data))
                with self.assertRaises(ValueError): snapshot.evidence_references([report], root)
            report.write_text('{"status":"PASS"}')
            with self.assertRaises(ValueError): snapshot.evidence_references([report, report], root)

    def test_report_outside_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp); root = parent / "repo"; root.mkdir()
            report = parent / "outside.json"; report.write_text('{"status":"PASS"}')
            with self.assertRaises(ValueError): snapshot.evidence_references([report], root)

    def test_snapshot_directory_does_not_claim_parent_repository_head(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(snapshot.subprocess, "check_output", return_value=str(root.parent)):
                self.assertIsNone(snapshot.source_revision(root)["head"])

    def test_failed_regeneration_replaces_previous_success_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); out = root / "out"
            out.mkdir(); (out / "capabilities.json").write_text('{"status":"PASS","routes":["old"]}')
            (out / "README.md").write_text("old success")
            with patch.object(capabilities, "ROOT", root):
                self.assertEqual(capabilities.main(["--output", str(out)]), 1)
            for filename in ("capabilities.json", "release_manifest.json", "result.json", "capability_backlog.json"):
                self.assertEqual(json.loads((out / filename).read_text())["status"], "FAIL")
            self.assertNotIn("old success", (out / "README.md").read_text(encoding="utf-8"))

    def test_unknown_template_backlog_does_not_invent_product_decisions(self):
        row = {"source": "audio_direct", "event": "EVT_TEST", "context": "default", "executor_behaviors": ["absent"]}
        row = snapshot.describe_route(row, {"behaviors": {}})
        result = snapshot.backlog({"routes": [row], "supplemental_routes": []})
        self.assertEqual(result["entries"][0]["decision"], "UNDECIDED")
        self.assertEqual(row["acceptance"]["hardware"], "NOT_RECORDED")


if __name__ == "__main__":
    unittest.main()
