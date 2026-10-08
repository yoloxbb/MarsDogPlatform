"""Canonical storage and compatibility reads must not select another deployment."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import model_assets


class ModelDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.location = patch.object(model_assets, "ROOT", self.root)
        self.location.start()
        self.addCleanup(self.location.stop)

    def legacy(self, kind):
        relative = {
            "voice": "cpu-20260929/voice-replay.json",
            "intent": "qwen2.5-0.5b-instruct/intent-replay.json",
        }[kind]
        path = self.root / "out/models" / relative
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        return path

    def test_fresh_checkout_defaults(self):
        self.assertEqual(model_assets.model_directory(), self.root / "models")
        self.assertEqual(model_assets.default_manifest("voice"), self.root / "models/cpu-20260929/voice-replay.json")
        self.assertEqual(model_assets.default_manifest("intent"), self.root / "models/llm/qwen2.5-0.5b-instruct/intent-replay.json")

    def test_existing_cpu_assets_remain_readable_with_notice(self):
        for kind in ("voice", "intent"):
            legacy = self.legacy(kind)
            with self.assertWarnsRegex(UserWarning, "existing CPU assets"):
                self.assertEqual(model_assets.default_manifest(kind), legacy)
            self.assertEqual(legacy.read_text(), "{}")

    def test_canonical_bundle_does_not_fall_back_when_incomplete(self):
        self.legacy("voice")
        target = self.root / "models/cpu-20260929/voice-replay.json"
        target.parent.mkdir(parents=True)
        self.assertEqual(model_assets.default_manifest("voice"), target)

    def test_explicit_external_root_never_uses_legacy_assets(self):
        self.legacy("voice")
        os.environ["MARSDOG_MODEL_DIR"] = str(self.root / "external")
        self.assertEqual(model_assets.default_manifest("voice"), self.root / "external/cpu-20260929/voice-replay.json")

    def test_relative_environment_root_is_rejected(self):
        os.environ["MARSDOG_MODEL_DIR"] = "models"
        with self.assertRaisesRegex(ValueError, "absolute"):
            model_assets.model_directory()
