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
        """安装后应提供时间、需求、情绪和性格节点入口。"""
        setupText = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")

        self.assertIn("time_controller_node = marsdog_ros2.time_controller_node:main", setupText)
        self.assertIn("internal_need_node = marsdog_ros2.internal_need_node:main", setupText)
        self.assertIn("emotion_engine_node = marsdog_ros2.emotion_engine_node:main", setupText)
        self.assertIn("personality_node = marsdog_ros2.personality_node:main", setupText)
        self.assertNotIn("behavior_node = marsdog_ros2.behavior_node:main", setupText)

    def test_internal_need_emotion_launch_file_is_declared(self):
        """联调 launch 文件应安装并启动四个节点。"""
        launchFile = PROJECT_ROOT / "marsdog_ros2" / "launch" / "internal_need_emotion.launch.py"
        setupText = (PROJECT_ROOT / "setup.py").read_text(encoding="utf-8")
        launchText = launchFile.read_text(encoding="utf-8")

        self.assertTrue(launchFile.exists())
        self.assertIn('glob("marsdog_ros2/launch/*.launch.py")', setupText)
        self.assertIn('executable="time_controller_node"', launchText)
        self.assertIn('executable="personality_node"', launchText)
        self.assertIn('executable="internal_need_node"', launchText)
        self.assertIn('executable="emotion_engine_node"', launchText)
        self.assertIn('"time_scale"', launchText)
        self.assertNotIn('"time_mode"', launchText)
        self.assertIn('"virtual_start_time"', launchText)
        self.assertIn('"random_seed"', launchText)

    def test_time_scale_parameter_replaces_fixed_time_modes(self):
        """时间节点应只暴露 1-24 整数倍率参数。"""
        timeNodeText = (
            PROJECT_ROOT / "marsdog_ros2" / "time_controller_node.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"time_scale"', timeNodeText)
        self.assertIn("IntegerRange(from_value=1, to_value=24, step=1)", timeNodeText)
        self.assertNotIn('"time_mode"', timeNodeText)

    def test_calculation_nodes_consume_authoritative_time_topic(self):
        """需求和情绪节点应消费统一时间 Topic，不再自建自然更新定时器。"""
        needNodeText = (PROJECT_ROOT / "marsdog_ros2" / "internal_need_node.py").read_text(
            encoding="utf-8"
        )
        emotionNodeText = (PROJECT_ROOT / "marsdog_ros2" / "emotion_engine_node.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"/simulation/time_state"', needNodeText)
        self.assertIn('"/simulation/time_state"', emotionNodeText)
        self.assertNotIn("GetRealIntervalValue(600.0)", needNodeText)
        self.assertNotIn("GetRealIntervalValue(1.0)", emotionNodeText)

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

    def test_calculation_nodes_shutdown_cleanly(self):
        """计算节点应容忍 launch 触发的外部关闭，避免重复 shutdown。"""
        for nodeFile in ("internal_need_node.py", "emotion_engine_node.py"):
            nodeText = (
                PROJECT_ROOT / "marsdog_ros2" / nodeFile
            ).read_text(encoding="utf-8")

            self.assertIn("ExternalShutdownException", nodeText)
            self.assertIn("if rclpy.ok():", nodeText)


if __name__ == "__main__":
    unittest.main()
