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
                if "/behavior/" in path:
                    changed["command_handshake"]["candidates"] = ["sit_down"]
                elif "/action/" in path:
                    changed["behaviors"]["eatNormally"]["stages"][0]["candidates"][0]["unit_id"] = "ACT_BASIC_SIT"
                elif path == "modules/voice/config/voice.yaml":
                    changed["providers"]["audio"]["config"]["vad_threshold"] = 0.75
                else:
                    changed["commands"][0]["command_id"] = "CMD_WRONG"
                with self.assertRaisesRegex(AssertionError, "semantics changed"):
                    assert_reviewed_config(changed, record, record["original_sha256"])
                with self.assertRaisesRegex(AssertionError, "historical source evidence"):
                    assert_reviewed_config(value, record, "wrong_original_hash")

    def test_live_extraction_matches_committed_graph(self):
        expected = json.loads((ROOT / "interfaces/naming/catalog.json").read_text())
        self.assertEqual(collect(ROOT), expected)


if __name__ == "__main__":
    unittest.main()
