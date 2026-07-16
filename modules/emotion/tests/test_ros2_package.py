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

    def test_internal_need_emotion_launch_file_is_declared(self):
        """联调 launch 文件应安装并启动三个计算节点。"""
        launchFile = PROJECT_ROOT / "marsdog_ros2" / "launch" / "internal_need_emotion.launch.py"
        setupText = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
        launchText = launchFile.read_text(encoding="utf-8")

        self.assertTrue(launchFile.exists())
        self.assertIn('glob("marsdog_ros2/launch/*.launch.py")', setupText)
        self.assertIn('executable="personality_node"', launchText)
        self.assertIn('executable="internal_need_node"', launchText)
        self.assertIn('executable="emotion_engine_node"', launchText)
        self.assertIn('"time_mode"', launchText)
        self.assertIn('"virtual_start_time"', launchText)
        self.assertIn('"random_seed"', launchText)

    def test_calculation_nodes_publish_time_context(self):
        """四类状态与事件输出都应通过统一时间上下文包装。"""
        needNodeText = (PROJECT_ROOT / "marsdog_ros2" / "internal_need_node.py").read_text(
            encoding="utf-8"
        )
        emotionNodeText = (PROJECT_ROOT / "marsdog_ros2" / "emotion_engine_node.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(needNodeText.count("GetMessageWithTimeContextValue("), 2)
        self.assertEqual(emotionNodeText.count("GetMessageWithTimeContextValue("), 2)


if __name__ == "__main__":
    unittest.main()
