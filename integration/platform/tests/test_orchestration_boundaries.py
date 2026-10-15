"""Prevent orchestration from silently growing a dependency on the ROS shell."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]


class OrchestrationBoundaries(unittest.TestCase):
    def test_core_reads_only_declared_state_and_ports(self):
        for relative in ('modules/voice/marsdog_voice_interaction/core/speech_pipeline.py',
                         'modules/action/marsdog_action_executor/goal_execution.py'):
            tree=ast.parse((ROOT/relative).read_text())
            with self.subTest(component=relative):
                attrs={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)
                       and isinstance(n.value,ast.Name) and n.value.id=='self'}
                self.assertEqual(attrs,{'ports','state'})
                for n in ast.walk(tree):
                    if isinstance(n,ast.ImportFrom):
                        self.assertNotIn('ros_node',n.module or '')
                        self.assertFalse((n.module or '').startswith('rclpy'))
                    if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='getattr':
                        self.assertFalse(isinstance(n.args[0],ast.Name) and n.args[0].id=='self')

    def test_navigation_core_does_not_import_voice_type(self):
        paths=('robotics/ros2/src/waypoint_nav/waypoint_nav/waypoint_nav_dispatcher.py',
               'modules/action/marsdog_action_executor/adapters/waypoint_nav_adapter.py')
        for relative in paths:
            tree=ast.parse((ROOT/relative).read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom):
                    self.assertFalse((n.module or '').startswith('marsdog_voice_interaction'))
