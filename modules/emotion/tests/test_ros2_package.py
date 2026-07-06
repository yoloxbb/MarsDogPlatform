import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Ros2PackageTest(unittest.TestCase):
    def test_ros2_package_metadata_exists(self):
        """ROS2 ament_python 包应具备标准安装元数据。"""
        packageXml = PROJECT_ROOT / "package.xml"
        setupPy = PROJECT_ROOT / "setup.py"
        setupCfg = PROJECT_ROOT / "setup.cfg"
        resourceMarker = PROJECT_ROOT / "resource" / "marsdog_behavior"

        self.assertTrue(packageXml.exists())
        self.assertTrue(setupPy.exists())
        self.assertTrue(setupCfg.exists())
        self.assertTrue(resourceMarker.exists())
        self.assertEqual(ElementTree.parse(packageXml).findtext("name"), "marsdog_behavior")

    def test_calculation_node_console_entries_are_declared(self):
        """安装后应提供需求、情绪和性格计算节点入口。"""
        setupText = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")

        self.assertIn("internal_need_node = marsdog_ros2.internal_need_node:main", setupText)
        self.assertIn("emotion_engine_node = marsdog_ros2.emotion_engine_node:main", setupText)
        self.assertIn("personality_node = marsdog_ros2.personality_node:main", setupText)
        self.assertNotIn("behavior_node = marsdog_ros2.behavior_node:main", setupText)


if __name__ == "__main__":
    unittest.main()
