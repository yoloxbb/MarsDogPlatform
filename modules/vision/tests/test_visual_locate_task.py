from types import SimpleNamespace

from marsdog_vision_interaction.core.visual_target_manager import (
    VisualTargetManager,
)
from marsdog_vision_interaction.nodes.vision_interaction_node import (
    VisionInteractionNode,
)


def _vision_node(target_manager):
    return SimpleNamespace(
        _target_manager=target_manager,
        _target_current_timeout_sec=0.35,
    )


def test_locate_person_once_returns_a_current_visual_target_only():
    manager = VisualTargetManager(vision_epoch="visual-only")
    manager.update_vision([{
        "x": 0.2,
        "y": 0.1,
        "w": 0.4,
        "h": 0.8,
        "confidence": 0.9,
    }], [])
    target_id = manager.get_active_dict()["target_id"]

    result = VisionInteractionNode._locate_person_once(
        _vision_node(manager), {"target_id": target_id}
    )

    assert result["ok"] is True
    assert result["target_id"] == target_id
    assert result["target"]["target_id"] == target_id
    assert result["target"]["tracking_state"] == "tracking"
    assert set(result) == {"ok", "target_id", "target"}


def test_locate_person_once_rejects_missing_or_unknown_target():
    manager = VisualTargetManager(vision_epoch="visual-only")
    node = _vision_node(manager)

    missing_id = VisionInteractionNode._locate_person_once(node, {})
    unknown_id = VisionInteractionNode._locate_person_once(
        node, {"target_id": "visual-only:human:999"}
    )

    assert missing_id["ok"] is False
    assert missing_id["error_code"] == "person_target_not_found"
    assert unknown_id["ok"] is False
    assert unknown_id["error_code"] == "person_target_not_found"
