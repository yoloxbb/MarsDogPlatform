"""Components extracted behind compatible node entrypoints; test tooling only."""
import hashlib
import json

COMPONENTS = {
    "voice": [
        "marsdog_voice_interaction.core.interaction_session",
        "marsdog_voice_interaction.core.speech_pipeline",
        "marsdog_voice_interaction.core.task_router",
        "marsdog_voice_interaction.messages.task_service",
    ],
    "vision": [
        "marsdog_vision_interaction.core.visual_snapshot",
        "marsdog_vision_interaction.core.task_router",
        "marsdog_vision_interaction.messages.visual_event_derivation",
        "marsdog_vision_interaction.messages.task_service",
    ],
    "emotion": ["marsdog_ros2.common.state_publication"],
    "behavior": [
        "marsdog_behavior.audio_contract",
        "marsdog_behavior.decision_trace",
        "marsdog_behavior.visual_event_consumer",
        "marsdog_behavior.state_subscriptions",
        "marsdog_behavior.voice_engagement",
    ],
    "action": [
        "marsdog_action_executor.perception_dispatch",
        "marsdog_action_executor.capability_report",
        "marsdog_action_executor.goal_contract",
        "marsdog_action_executor.action_messages",
        "marsdog_action_executor.goal_lifecycle",
        "marsdog_action_executor.goal_execution",
        "marsdog_action_executor.telemetry",
    ],
}


def check_installed_components(run, python, source):
    """Import wheel components without source/ROS; compare exact installed bytes."""
    names = COMPONENTS[source.name] + ["marsdog_observability", "marsdog_observability.runtime",
                                        "marsdog_observability.formatting", "marsdog_observability.ros",
                                        "marsdog_observability.logger", "marsdog_observability.sinks"]
    probe = """
import hashlib,importlib,importlib.util,json,pathlib,sys
assert importlib.util.find_spec('rclpy') is None
observed={}
for name in NAMES:
    module=importlib.import_module(name)
    path=pathlib.Path(module.__file__).resolve()
    assert path.is_relative_to(pathlib.Path(sys.prefix).resolve()), path
    observed[name]={'module_file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
assert not any(n.endswith('.ros_node') or '.nodes.' in n for n in sys.modules), 'ROS shell imported by component'
print(json.dumps(observed))
""".replace("NAMES", repr(names))
    observed = json.loads(run([str(python), "-B", "-c", probe]))
    assert set(observed) == set(names)
    for name in names:
        base = source.parents[1] / "packages/observability" if name.startswith("marsdog_observability") else source
        path = base / (name.replace(".", "/") + ".py")
        if not path.is_file():
            path = base / name.replace(".", "/") / "__init__.py"
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        assert observed[name]["sha256"] == expected, "Stale or missing component: " + name
    return observed
