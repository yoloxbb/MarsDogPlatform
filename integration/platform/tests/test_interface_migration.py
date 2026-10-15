"""Protect the approved public endpoint migration and its historical evidence."""
import ast
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from integration.naming.config_compatibility import restore_reviewed_interface_names

ROOT = Path(__file__).resolve().parents[3]


class InterfaceMigrationTests(unittest.TestCase):
    def test_registry_has_one_navigation_type_and_unique_endpoints(self):
        records = json.loads((ROOT / "interfaces/registry.json").read_text())["interfaces"]
        endpoints = {record["name"]: record["type"] for record in records}
        self.assertEqual(len(records), len(endpoints))
        self.assertEqual(endpoints["/navigation/task"], "marsdog_interfaces/srv/NavigationTask")
        self.assertEqual(endpoints["/action/execute_behavior"], "marsdog_interfaces/action/ExecuteBehavior")
        self.assertFalse(any(name.startswith(("/go2/", "/waypoint_nav/", "/execute_behavior")) for name in endpoints))

    def test_navigation_and_action_no_longer_depend_on_voice_or_private_action(self):
        for module in ("modules/action", "robotics/ros2/src/waypoint_nav"):
            root = ET.parse(ROOT / module / "package.xml").getroot()
            self.assertNotIn("marsdog_voice_interaction", {n.text for n in root})
        for relative in ("modules/action/marsdog_action_executor", "modules/behavior/marsdog_behavior",
                         "robotics/ros2/src/waypoint_nav/waypoint_nav"):
            for path in (ROOT / relative).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotEqual(node.module, "marsdog_action_executor.action", str(path))
        self.assertFalse((ROOT / "modules/action/action/ExecuteBehavior.action").exists())
        self.assertFalse((ROOT / "modules/action/marsdog_action_executor/adapters/navigation_task_wire.py").exists())
        self.assertFalse((ROOT / "robotics/ros2/src/waypoint_nav/waypoint_nav/legacy_voice_task.py").exists())

    def test_reviewed_name_changes_reject_unrelated_asset_edits(self):
        records = json.loads((ROOT / "integration/naming/interface_migration.json").read_text())["assets"]
        self.assertTrue(records)
        for path in records:
            contents = (ROOT / path).read_bytes()
            restore_reviewed_interface_names(contents, path)
            with self.assertRaisesRegex(AssertionError, "interface migration asset changed"):
                restore_reviewed_interface_names(contents + b"# unreviewed change", path)
