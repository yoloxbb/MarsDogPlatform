"""Test-only isolation/provenance helpers; no cross-module business imports."""
import argparse
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys

FAMILIES = {
    "voice": ("marsdog_voice_interaction",),
    "vision": ("marsdog_vision_interaction",),
    "behavior": ("marsdog_behavior", "bionic_dog_bt"),
    "emotion": ("marsdog_core", "marsdog_ros2"),
    "action": ("marsdog_action_executor",),
}


def serve(handlers, *, allow_ros=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=handlers, required=True)
    args = parser.parse_args()
    foreign = [prefix for stage, prefixes in FAMILIES.items() if stage != args.stage
               for prefix in prefixes if importlib.util.find_spec(prefix) is not None]
    ros_importable = importlib.util.find_spec("rclpy") is not None
    if foreign or ros_importable != allow_ros:
        raise RuntimeError("Pure worker requires independent environment: " + repr(foreign))
    request = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        observed, module_file = handlers[args.stage](request)
    foreign = [name for stage, prefixes in FAMILIES.items() if stage != args.stage
               for name in sys.modules
               if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)]
    if foreign:
        raise RuntimeError("Foreign business imports: " + repr(foreign))
    print(json.dumps({
        "observed": observed,
        "provenance": {"stage": args.stage, "pid": os.getpid(), "python": sys.executable,
                       "prefix": sys.prefix, "module_file": str(Path(module_file).resolve()),
                       "foreign_business_modules": foreign, "ros_importable": ros_importable},
    }, ensure_ascii=False, allow_nan=False))
