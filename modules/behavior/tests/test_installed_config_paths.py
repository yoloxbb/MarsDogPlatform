"""Installed-package regression without replacing existing configuration precedence."""
import sys
from types import ModuleType

from marsdog_behavior import config_paths


def test_explicit_config_keeps_priority_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSDOG_BEHAVIOR_CONFIG_DIR", str(tmp_path / "environment"))
    assert config_paths.get_config_dir(str(tmp_path / "explicit")) == tmp_path / "explicit"


def test_environment_keeps_priority_over_source(tmp_path, monkeypatch):
    monkeypatch.setenv("MARSDOG_BEHAVIOR_CONFIG_DIR", str(tmp_path))
    assert config_paths.get_config_dir() == tmp_path


def simulate_install(tmp_path, monkeypatch):
    monkeypatch.delenv("MARSDOG_BEHAVIOR_CONFIG_DIR", raising=False)
    monkeypatch.setattr(config_paths, "__file__", str(tmp_path / "site-packages/marsdog_behavior/config_paths.py"))
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    installed = tmp_path / "share/marsdog_behavior/config"
    installed.mkdir(parents=True)
    return installed


def test_wheel_default_without_ros(tmp_path, monkeypatch):
    installed = simulate_install(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "ament_index_python", None)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", None)
    assert config_paths.get_config_dir() == installed


def test_ros_share_still_precedes_wheel_prefix(tmp_path, monkeypatch):
    simulate_install(tmp_path, monkeypatch)
    ros_share = tmp_path / "ros-share"
    (ros_share / "config").mkdir(parents=True)
    packages = ModuleType("ament_index_python.packages")
    packages.get_package_share_directory = lambda _: str(ros_share)
    monkeypatch.setitem(sys.modules, "ament_index_python", ModuleType("ament_index_python"))
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", packages)
    assert config_paths.get_config_dir() == ros_share / "config"
