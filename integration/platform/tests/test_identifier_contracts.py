"""Regression tests for newly broken links, namespace collisions and stale evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import check_identifiers as checker
from identifier_catalog import FINGERPRINT_PATHS, fingerprints


def graph():
    return {
        "schema_version": 1, "source_sha256": {}, "categories": ["external_interaction"],
        "pools": {"command_handshake": ["give_paw"]},
        "routes": [{
            "source": "audio_direct", "event": "EVT_VOICE_COMMAND_SHAKE_HAND",
            "context": "default", "intent": "command_handshake", "selection": "intent_pool",
            "category": "external_interaction", "expected_command_id": "CMD_HAND",
            "bt_behaviors": ["give_paw"], "executor_behaviors": ["give_paw"],
        }],
        "voice_commands": [{"command_key": "HAND", "command_id": "CMD_HAND",
                            "event": "EVT_VOICE_COMMAND_SHAKE_HAND",
                            "product_action_label": "ACT_SHAKE_HAND"}],
        "social_reactions": [],
        "behaviors": {"give_paw": [{"stage_id": "action", "units": ["ACT_INTERACT_GIVE_PAW"]}]},
        "units": ["ACT_INTERACT_GIVE_PAW"],
    }


def exceptions():
    return {"schema_version": 1, "missing_templates": [], "legacy_spellings": [],
            "voice_without_route": [], "non_catalog_audio_routes": []}


class IdentifierContractTests(unittest.TestCase):
    def errors(self, catalog, allowed=None):
        return checker.validate(catalog, allowed or exceptions())["errors"]

    def test_product_label_is_not_an_action_unit_reference(self):
        self.assertEqual(self.errors(graph()), [])
        self.assertEqual(checker.validate(graph(), exceptions())["status"], "PASS")

    def test_new_missing_template_fails_but_explicit_old_gap_is_reported(self):
        catalog = graph()
        catalog["behaviors"] = {}
        key = "audio_direct|EVT_VOICE_COMMAND_SHAKE_HAND|default|give_paw"
        self.assertIn("unregistered missing_templates: " + key, self.errors(catalog))
        allowed = exceptions()
        allowed["missing_templates"] = [key]
        report = checker.validate(catalog, allowed)
        self.assertEqual(report["status"], "PASS_WITH_KNOWN_GAPS")
        self.assertEqual(report["counts"]["known_missing_template_routes"], 1)
        self.assertTrue(any("stale missing_templates" in e for e in self.errors(graph(), allowed)))

    def test_exception_for_one_context_cannot_hide_a_new_broken_route(self):
        catalog = graph()
        catalog["behaviors"] = {}
        allowed = exceptions()
        allowed["missing_templates"] = [
            "audio_direct|EVT_VOICE_COMMAND_SHAKE_HAND|default|give_paw"]
        new_route = deepcopy(catalog["routes"][0])
        new_route["context"] = "new_context"
        catalog["routes"].append(new_route)
        self.assertTrue(any("new_context" in e for e in self.errors(catalog, allowed)))

    def test_executor_override_is_checked_separately_from_bt_identity(self):
        catalog = graph()
        catalog["routes"][0]["executor_behaviors"] = ["missing_executor"]
        self.assertTrue(any("missing_executor" in e for e in self.errors(catalog)))

    def test_unknown_unit_cannot_hide_behind_a_registered_template(self):
        catalog = graph()
        catalog["units"] = []
        self.assertTrue(any("unknown action unit" in e for e in self.errors(catalog)))

    def test_voice_command_id_mismatch_and_duplicate_are_errors(self):
        catalog = graph()
        catalog["voice_commands"][0]["command_id"] = "CMD_WRONG"
        self.assertTrue(any("command_id mismatch" in e for e in self.errors(catalog)))
        catalog = graph()
        catalog["voice_commands"].append(deepcopy(catalog["voice_commands"][0]))
        self.assertTrue(any("duplicate voice" in e for e in self.errors(catalog)))

    def test_command_route_cannot_silently_drop_identity_validation(self):
        catalog = graph()
        catalog["routes"][0]["expected_command_id"] = None
        self.assertTrue(any("missing expected_command_id" in e for e in self.errors(catalog)))

    def test_missing_pool_and_category_do_not_look_like_valid_routes(self):
        catalog = graph()
        catalog["pools"] = {}
        catalog["routes"][0]["category"] = "unknown"
        errors = self.errors(catalog)
        self.assertTrue(any("intent pool" in e for e in errors))
        self.assertTrue(any("unknown category" in e for e in errors))

    def test_new_mixed_case_unit_requires_explicit_compatibility_review(self):
        catalog = graph()
        catalog["units"].append("ACT_Mixed_CASE")
        self.assertIn("unregistered legacy_spellings: unit|ACT_Mixed_CASE", self.errors(catalog))

    def test_social_reaction_must_reference_a_declared_emotion_route(self):
        catalog = graph()
        catalog["social_reactions"] = [{
            "event": "EVT_VOICE_COMMAND_PRAISE", "intent": "audio_react_praise",
            "category": "external_interaction", "expected_command_id": "CMD_PRAISE",
            "emotion_events": ["EMO_JOY_TRIGGERED"],
        }]
        self.assertTrue(any("missing emotion route" in e for e in self.errors(catalog)))

    def test_unreferenced_pool_is_visible_but_not_claimed_unreachable(self):
        catalog = graph()
        catalog["pools"]["internal_continuation"] = ["code_only_behavior"]
        report = checker.validate(catalog, exceptions())
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["findings"]["pools_not_selected_by_declared_routes"],
                         ["internal_continuation"])

    def test_source_and_generator_changes_invalidate_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in FINGERPRINT_PATHS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("old")
            catalog = graph()
            catalog["source_sha256"] = fingerprints(root)
            checker.check_freshness(catalog, root)
            (root / FINGERPRINT_PATHS[-1]).write_text("new")
            with self.assertRaisesRegex(ValueError, "sources changed"):
                checker.check_freshness(catalog, root)

    def test_invalid_refresh_cannot_write_catalog_or_expand_exceptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog_path = root / checker.CATALOG
            catalog_path.parent.mkdir(parents=True)
            catalog_path.write_text("preserved catalog")
            allowed_path = root / checker.EXCEPTIONS
            original = json.dumps(exceptions())
            allowed_path.write_text(original)
            broken = graph()
            broken["units"] = []
            completed = subprocess.CompletedProcess([], 0, json.dumps(broken), "")
            with patch.object(checker, "ROOT", root), \
                 patch.object(checker, "check_freshness"), \
                 patch.object(checker.subprocess, "run", return_value=completed), \
                 patch.object(sys, "argv", ["check_identifiers.py", "--refresh", "--python", sys.executable]):
                self.assertEqual(checker.main(), 1)
            self.assertEqual(catalog_path.read_text(), "preserved catalog")
            self.assertEqual(allowed_path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
