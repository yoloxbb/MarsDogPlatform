"""Guard source/ROS precedence and the new ordinary-wheel fallback."""
from pathlib import Path
from types import ModuleType
import sys
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

from marsdog_core import config_loader


class InstalledConfigLookupTest(unittest.TestCase):
    def test_source_still_wins_over_installed_prefix(self):
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            with patch.object(config_loader, "DEFAULT_CONFIG_DIR", source):
                self.assertEqual(config_loader._GetDefaultConfigDir(), source)

    def test_wheel_prefix_is_used_without_ros(self):
        with TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            configs = prefix / "share/marsdog_need_emotion/configs"
            configs.mkdir(parents=True)
            with patch.object(config_loader, "DEFAULT_CONFIG_DIR", prefix / "missing"), \
                 patch.object(sys, "prefix", str(prefix)), \
                 patch.dict(sys.modules, {"ament_index_python": None,
                                          "ament_index_python.packages": None}):
                self.assertEqual(config_loader._GetDefaultConfigDir(), configs)

    def test_ros_share_still_wins_over_wheel_prefix(self):
        with TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            wheel_configs = prefix / "share/marsdog_need_emotion/configs"
            wheel_configs.mkdir(parents=True)
            packages = ModuleType("ament_index_python.packages")
            packages.get_package_share_directory = lambda _: str(prefix / "ros-share")
            with patch.object(config_loader, "DEFAULT_CONFIG_DIR", prefix / "missing"), \
                 patch.object(sys, "prefix", str(prefix)), \
                 patch.dict(sys.modules, {"ament_index_python": ModuleType("ament_index_python"),
                                          "ament_index_python.packages": packages}):
                self.assertEqual(config_loader._GetDefaultConfigDir(), prefix / "ros-share/configs")

    def test_unregistered_ros_package_falls_back_to_wheel(self):
        with TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            configs = prefix / "share/marsdog_need_emotion/configs"
            configs.mkdir(parents=True)
            packages = ModuleType("ament_index_python.packages")
            def missing(_):
                raise LookupError("Package is not in AMENT_PREFIX_PATH")
            packages.get_package_share_directory = missing
            with patch.object(config_loader, "DEFAULT_CONFIG_DIR", prefix / "missing"), \
                 patch.object(sys, "prefix", str(prefix)), \
                 patch.dict(sys.modules, {"ament_index_python": ModuleType("ament_index_python"),
                                          "ament_index_python.packages": packages}):
                self.assertEqual(config_loader._GetDefaultConfigDir(), configs)
