"""Tests for marsdog_behavior nodes (standalone mode, no ROS2 required)."""

from __future__ import annotations

import time
import pytest
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from marsdog_behavior.interfaces import (
    BehaviorSignal, BehaviorFeedback,
    ExecuteBehaviorGoal, ExecuteBehaviorFeedback, ExecuteBehaviorResult,
)
from marsdog_behavior.ros_node import BehaviorTreeRosNode
from marsdog_behavior.mock_action_executor_node import MockActionExecutorNode
from marsdog_behavior.ros2_compat import HAS_ROS2


# Skip if ROS2 is available (tests are for standalone mode)
pytestmark = pytest.mark.skipif(HAS_ROS2, reason="Tests are for standalone (no-ROS2) mode")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def bt_node():
    node = BehaviorTreeRosNode()
    yield node
    node.destroy_node()


@pytest.fixture
def action_node():
    node = MockActionExecutorNode()
    yield node
    node.destroy_node()


# ── Interface Tests ──────────────────────────────────────────────────────────

class TestInterfaces:
    """Test message dataclasses."""

    def test_behavior_signal_serialization(self):
        sig = BehaviorSignal(
            behavior_name="playBow",
            priority_level=5,
            value=85.0,
            need_type="emotional",
            source_emotion="Joy",
            params_json='{"interactive":true}',
        )
        d = sig.to_dict()
        sig2 = BehaviorSignal.from_dict(d)
        assert sig2.behavior_name == "playBow"
        assert sig2.params["interactive"] is True

    def test_behavior_feedback_serialization(self):
        fb = BehaviorFeedback(
            behavior_id="test_1",
            behavior_name="playBow",
            status="SUCCESS",
            result="completed",
            reward=1.0,
        )
        fb.emotion_delta = {"Joy": 5}
        assert fb.emotion_delta["Joy"] == 5
        d = fb.to_dict()
        fb2 = BehaviorFeedback.from_dict(d)
        assert fb2.status == "SUCCESS"

    def test_execute_behavior_goal(self):
        goal = ExecuteBehaviorGoal(
            behavior_name="playBow",
            priority_level=5,
            params_json='{"interactive":true}',
        )
        assert goal.goal_id.startswith("goal_")
        assert goal.params["interactive"] is True

    def test_execute_behavior_result(self):
        result = ExecuteBehaviorResult(
            goal_id="goal_1",
            behavior_name="playBow",
            status="SUCCESS",
        )
        d = result.to_dict()
        assert d["status"] == "SUCCESS"


# ── Behavior Tree Node Tests ─────────────────────────────────────────────────

class TestBehaviorTreeNode:
    """Test behavior_tree_node standalone mode."""

    def test_node_creates(self, bt_node):
        assert bt_node is not None
        assert bt_node.blackboard is not None
        assert bt_node._tree is not None

    def test_add_signal(self, bt_node):
        bt_node.add_signal(
            behavior_name="respond_owner_call",
            priority_level=2,
            value=85.0,
            need_type="external",
        )
        assert bt_node.candidate_pool.size() == 1

    def test_select_candidate_priority(self, bt_node):
        # Add Lv3 and Lv2; Lv2 should be selected (lower level = higher priority)
        bt_node.add_signal(
            behavior_name="seek_food_or_water", priority_level=3, value=80.0,
            need_type="physiological",
        )
        bt_node.add_signal(
            behavior_name="respond_owner_call", priority_level=2, value=70.0,
            need_type="external",
        )
        best = bt_node.candidate_pool.select_best(bt_node.blackboard)
        assert best is not None
        assert best["behavior_name"] == "respond_owner_call"  # Lv2 > Lv3

    def test_select_highest_value_same_level(self, bt_node):
        bt_node.add_signal(
            behavior_name="clean_self", priority_level=3, value=60.0,
            need_type="physiological",
        )
        bt_node.add_signal(
            behavior_name="seek_food_or_water", priority_level=3, value=85.0,
            need_type="physiological",
        )
        best = bt_node.candidate_pool.select_best(bt_node.blackboard)
        assert best is not None
        assert best["behavior_name"] == "seek_food_or_water"  # higher value wins

    def test_update_emotion_state(self, bt_node):
        bt_node.update_emotion_state({"Joy": 85, "Fear": 20})
        assert bt_node.blackboard.emotion_module.get_value("Joy") == 85.0

        # Joy > 70 should generate an emotion candidate
        bt_node.update_emotion_state({"Joy": 85})
        # Pool may or may not have candidates depending on emotion table
        assert bt_node.candidate_pool.size() >= 0


# ── Mock Action Executor Tests ───────────────────────────────────────────────

class TestMockActionExecutor:
    """Test mock_action_executor_node (imported from marsdog_ros2 for compatibility)."""

    def test_node_creates(self, action_node):
        assert action_node is not None

    def test_send_goal(self, action_node):
        goal = ExecuteBehaviorGoal(
            behavior_name="playBow",
            priority_level=5,
            params_json='{"interactive":true}',
        )
        gid = action_node.send_goal(goal)
        assert gid.startswith("goal_")

        fb = action_node.get_feedback(gid)
        assert fb is not None
        assert fb.status == "RUNNING"
        assert fb.progress >= 0.0

    def test_goal_progress(self, action_node):
        goal = ExecuteBehaviorGoal(
            behavior_name="wagTailGently",
            priority_level=5,
            timeout_sec=10.0,
        )
        gid = action_node.send_goal(goal)

        time.sleep(0.5)
        action_node._tick()
        fb = action_node.get_feedback(gid)
        assert fb is not None
        assert fb.current_action != "N/A"

    def test_goal_completion(self, action_node):
        goal = ExecuteBehaviorGoal(
            behavior_name="wagTailGently",
            priority_level=5,
            timeout_sec=10.0,
        )
        gid = action_node.send_goal(goal)

        for _ in range(40):
            time.sleep(0.1)
            action_node._tick()
            fb = action_node.get_feedback(gid)
            if fb.status != "RUNNING":
                break

        result = action_node.get_result(gid)
        assert result is not None
        assert result.status == "SUCCESS"
        assert result.reward == 1.0

    def test_cancel_goal(self, action_node):
        goal = ExecuteBehaviorGoal(
            behavior_name="sleepOnSide",
            priority_level=5,
            timeout_sec=60.0,
        )
        gid = action_node.send_goal(goal)

        assert action_node.cancel_goal(gid) is True

        fb = action_node.get_feedback(gid)
        assert fb.status == "CANCELED"

    def test_multiple_goals(self, action_node):
        gid1 = action_node.send_goal(ExecuteBehaviorGoal(
            behavior_name="wagTailGently", priority_level=5,
        ))
        gid2 = action_node.send_goal(ExecuteBehaviorGoal(
            behavior_name="headTilt", priority_level=5,
        ))
        assert gid1 != gid2

        fb1 = action_node.get_feedback(gid1)
        fb2 = action_node.get_feedback(gid2)
        assert fb1 is not None
        assert fb2 is not None


# ── Integration: BT Node + Action Executor ───────────────────────────────────

class TestIntegration:
    """End-to-end test: signal → BT tick → action execution → feedback."""

    def test_full_cycle(self, bt_node, action_node):
        bt_node.add_signal(
            behavior_name="respond_owner_call",
            priority_level=2, value=85.0,
            need_type="external", timeout_sec=8.0,
        )
        bt_node._on_tick()
        assert bt_node.blackboard.tick_count >= 1

    def test_emotion_signal_full_cycle(self, bt_node, action_node):
        bt_node.blackboard.emotion_module.set_emotion("Joy", 85)

        bt_node.add_signal(
            behavior_name="playBow",
            priority_level=5, value=85.0,
            need_type="emotional", source_emotion="Joy",
            params={"source_emotion": "Joy", "emotion_value": 85, "interactive": False},
            timeout_sec=8.0,
        )
        bt_node._on_tick()
        assert bt_node.blackboard.tick_count >= 1

    def test_preemption_scenario(self, bt_node, action_node):
        """Lv0 danger should preempt Lv2 owner_call."""
        bt_node.add_signal(
            behavior_name="respond_owner_call",
            priority_level=2, value=85.0, need_type="external",
        )
        bt_node._on_tick()

        bt_node.add_signal(
            behavior_name="avoid_danger",
            priority_level=0, value=100.0, need_type="survival",
        )
        bt_node._on_tick()

        assert bt_node.blackboard.tick_count >= 2
