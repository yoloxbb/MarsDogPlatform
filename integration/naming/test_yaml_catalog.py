"""Run with an existing module Python that provides PyYAML; no business imports."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from identifier_catalog import ROOT, collect, read_yaml
sys.path.insert(0, str(ROOT))
from integration.naming.config_compatibility import FIXTURE, assert_reviewed_config


class YamlCatalogTests(unittest.TestCase):
    def test_duplicate_mapping_key_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.yaml"
            path.write_text("behaviors:\n  sit: one\n  sit: two\n")
            with self.assertRaisesRegex(ValueError, "duplicate YAML key 'sit'"):
                read_yaml(path)

    def test_yaml_anchors_keep_both_named_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shared.yaml"
            path.write_text("first: &shared\n  stages: [one, two]\nsecond: *shared\n")
            value = read_yaml(path)
            self.assertEqual(set(value), {"first", "second"})
            self.assertEqual(value["first"], value["second"])

    def test_reviewed_defaults_reject_behavior_or_unit_changes(self):
        records = json.loads(FIXTURE.read_text())["configs"]
        for path, record in records.items():
            with self.subTest(path=path):
                value = read_yaml(ROOT / path)
                assert_reviewed_config(value, record, record["original_sha256"])
                changed = deepcopy(value)
                if path == "modules/behavior/config/behaviors.yaml":
                    changed["behaviors"]["dance"]["cooldown_sec"] = 999
                elif path == "modules/behavior/config/event_intent_map.yaml":
                    changed["audio_direct"]["EVT_VOICE_COMMAND_DANCE"]["sub_priority"] = 999
                elif "/behavior/" in path:
                    changed["command_handshake"]["candidates"] = ["sit_down"]
                elif "/action/" in path:
                    changed["behaviors"]["eatNormally"]["stages"][0]["candidates"][0]["unit_id"] = "ACT_BASIC_SIT"
                elif path == "modules/voice/config/voice.yaml":
                    changed["providers"]["audio"]["config"]["vad_threshold"] = 0.75
                elif path == "modules/vision/config/vision.yaml":
                    changed['topics']['camera_stale_timeout_sec'] = 999
                elif path == "robotics/ros2/src/robot_slam_bringup/config/nav.yaml":
                    changed['velocity_smoother']['ros__parameters']['max_velocity'][0] = 999
                else:
                    changed["commands"][0]["command_id"] = "CMD_WRONG"
                with self.assertRaisesRegex(AssertionError, "semantics changed"):
                    assert_reviewed_config(changed, record, record["original_sha256"])
                with self.assertRaisesRegex(AssertionError, "historical source evidence"):
                    assert_reviewed_config(value, record, "wrong_original_hash")

    def test_reviewed_expression_budgets_allow_only_the_exact_scalars(self):
        path = "modules/behavior/config/behaviors.yaml"
        record = json.loads(FIXTURE.read_text())["configs"][path]
        value = read_yaml(ROOT / path)
        self.assertEqual(len(record["timeout_overrides"]), 33)
        for name, change in record["timeout_overrides"].items():
            changed = deepcopy(value)
            changed["behaviors"][name]["timeout_sec"] = change["before"]
            # Some existing 15s defaults need no numeric change; they are still explicit.
            if change["before"] != change["after"]:
                with self.assertRaisesRegex(AssertionError, "semantics changed"):
                    assert_reviewed_config(changed, record, record["original_sha256"])
        changed = deepcopy(value)
        changed["behaviors"]["sit_down"]["timeout_sec"] = 999
        with self.assertRaisesRegex(AssertionError, "semantics changed"):
            assert_reviewed_config(changed, record, record["original_sha256"])
        event_path = "modules/behavior/config/event_intent_map.yaml"
        event_record = json.loads(FIXTURE.read_text())["configs"][event_path]
        self.assertEqual(event_record['timeout_section'], 'audio_direct')
        self.assertEqual(len(event_record['timeout_overrides']), 33)
        events = read_yaml(ROOT / event_path)
        events['audio_direct']['EVT_VOICE_COMMAND_DANCE']['timeout_sec'] = 1
        with self.assertRaisesRegex(AssertionError, "semantics changed"):
            assert_reviewed_config(events, event_record, event_record['original_sha256'])

    def test_live_extraction_matches_committed_graph(self):
        expected = json.loads((ROOT / "interfaces/naming/catalog.json").read_text())
        self.assertEqual(collect(ROOT), expected)

    def test_each_reviewed_path_rejects_value_or_presence_drift(self):
        records = json.loads(FIXTURE.read_text())["configs"]
        for path, record in records.items():
            for change in record.get('path_changes', []):
                with self.subTest(path=path, field=change['path']):
                    value = read_yaml(ROOT / path)
                    cursor = value
                    for key in change['path'][:-1]:
                        cursor = cursor[key]
                    key = change['path'][-1]
                    if change['after_present']:
                        cursor.pop(key)
                    else:
                        cursor[key] = change['before']
                    with self.assertRaisesRegex(AssertionError, 'semantics changed'):
                        assert_reviewed_config(value, record, record['original_sha256'])


if __name__ == "__main__":
    unittest.main()
