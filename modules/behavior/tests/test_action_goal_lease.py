"""Tree renews a long Goal by behavior identity after voice idle."""

import json
import sys
from types import ModuleType
from types import SimpleNamespace as NS

from marsdog_behavior.ros_node import BehaviorTreeRosNode


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(json.loads(message.data))


def test_voice_session_identity_is_not_needed_to_renew_goal(monkeypatch):
    # Exercise the ROS publishing boundary on hosts without ROS installed.
    std_msgs = ModuleType("std_msgs")
    std_msgs.msg = ModuleType("std_msgs.msg")
    std_msgs.msg.String = type("String", (), {"data": ""})
    monkeypatch.setitem(sys.modules, "std_msgs", std_msgs)
    monkeypatch.setitem(sys.modules, "std_msgs.msg", std_msgs.msg)
    publisher = _Publisher()
    node = NS(
        _ros2_ready=True,
        _goal_lease_pub=publisher,
        _blackboard=NS(current_behavior=NS(
            behavior_name="follow_owner", behavior_id="goal-42",
            params={"interaction_id": "closed-voice-session"},
        )),
    )

    BehaviorTreeRosNode._renew_action_goal_lease(node)

    assert publisher.messages == [{
        "schema_version": 1,
        "goal_id": "goal-42",
        "behavior_id": "goal-42",
    }]
    node._blackboard.current_behavior = None
    BehaviorTreeRosNode._renew_action_goal_lease(node)
    assert len(publisher.messages) == 1
