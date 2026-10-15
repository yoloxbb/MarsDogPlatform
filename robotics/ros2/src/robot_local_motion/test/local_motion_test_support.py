"""Load pure source cores without shadowing the generated ROS interface package."""
import importlib.util
from pathlib import Path
import sys

package=Path(__file__).resolve().parents[1]/'robot_local_motion'
name='_local_motion_under_test'
if name not in sys.modules:
    spec=importlib.util.spec_from_file_location(name,package/'__init__.py',submodule_search_locations=[str(package)])
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module)
from _local_motion_under_test.core import Limits, MotionTask, Pose, Target, parse_parameters
from _local_motion_under_test.guard import StampGuard, StopCheck
