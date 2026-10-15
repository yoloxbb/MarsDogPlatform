"""The public debug publishers never recreate retired business-topic aliases."""
from types import SimpleNamespace

from marsdog_action_executor import debug_publishers


def test_debug_publishes_only_canonical_topics(monkeypatch):
    topics = {}
    monkeypatch.setenv("MARSDOG_LEGACY_DEBUG_TOPICS", "1")
    monkeypatch.setattr(debug_publishers, "HAS_ROS2", True)
    monkeypatch.setattr(debug_publishers, "String", lambda **fields: SimpleNamespace(**fields), raising=False)

    class Node:
        def create_publisher(self, kind, topic, depth):
            messages = topics.setdefault(topic, [])
            return SimpleNamespace(publish=messages.append)

    publishers = debug_publishers.DebugPublishers(Node())
    payload = SimpleNamespace(to_json=lambda: '{"goal_id":"one"}')
    publishers.publish_goal(payload)
    publishers.publish_feedback(payload)
    publishers.publish_result(payload)
    assert set(topics) == {"/debug/execute_behavior/goal", "/debug/execute_behavior/feedback",
                           "/debug/execute_behavior/result"}
    assert all([message.data for message in messages] == ['{"goal_id":"one"}']
               for messages in topics.values())
