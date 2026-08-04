"""Tree builder: constructs the complete behavior tree from config."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
except ImportError:  # pragma: no cover
    Console = None

from .behavior_tree_node import Node, Selector, Sequence
from .blackboard import Blackboard
from .conditions import ActiveLevelCondition, BehaviorRelevanceCondition
from .actions import ExecuteActiveBehavior, ExecutorInterface
from .mock_action_executor import MockActionExecutor  # ⚠️ TEMP: swap to ActionClientAdapter
from .mock_input_provider import MockInputProvider
from .yaml_loader import YAMLLoader
from .emotion_module import EmotionModule
from .constants import LEVEL_NAMES


def build_tree(
    blackboard: Blackboard,
    executor: ExecutorInterface,  # ⚠️ any ExecutorInterface impl works (mock or ActionClient)
) -> Selector:
    """Build the full behavior tree.

    Structure:
    Root Selector(memory=False)
    ├── Lv0_System → Sequence[ActiveLevelCondition(0), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    ├── Lv1_PhysioUrgent → Sequence[ActiveLevelCondition(1), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    ├── Lv2_ExternalInteraction → Sequence[ActiveLevelCondition(2), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    ├── Lv3_PhysioNormal → Sequence[ActiveLevelCondition(3), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    ├── Lv4_Psychological → Sequence[ActiveLevelCondition(4), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    ├── Lv5_EmotionExpression → Sequence[ActiveLevelCondition(5), BehaviorRelevanceCondition, ExecuteActiveBehavior]
    └── Lv6_Idle → Sequence[ActiveLevelCondition(6), BehaviorRelevanceCondition, ExecuteActiveBehavior]

    BehaviorRelevanceCondition gates emotion-triggered behaviors:
    if V2 state reports ``triggered=false`` for the source emotion, the
    condition fails and discards the queued behavior.
    """
    root = Selector("Root", memory=False)

    for level in range(7):
        level_name = LEVEL_NAMES[level]
        seq = Sequence(f"Seq_{level_name}")

        condition = ActiveLevelCondition(f"CheckLv{level}", blackboard, level)
        relevance = BehaviorRelevanceCondition(f"RelevantLv{level}", blackboard)
        action = ExecuteActiveBehavior(f"ExecLv{level}", blackboard, executor)

        seq.add_child(condition)
        seq.add_child(relevance)
        seq.add_child(action)
        root.add_child(seq)

    return root


def create_runtime(
    config_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> tuple[Selector, Blackboard, MockActionExecutor, MockInputProvider, YAMLLoader]:
    """Create and wire up the full runtime.

    Returns (root, blackboard, executor, input_provider, yaml_loader).
    """
    # Resolve config path
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / "config" / "behaviors.yaml")

    # Load YAML config
    loader = YAMLLoader(config_path)

    # Create blackboard (includes EmotionModule internally)
    blackboard = Blackboard()

    # Create executor
    executor = MockActionExecutor(loader)

    # Create input provider with all upstream module references
    input_provider = MockInputProvider(
        blackboard, blackboard.emotion_module, blackboard.need_module,
        blackboard.perception_client,
    )

    # Build tree
    root = build_tree(blackboard, executor)

    # Setup console
    root.setup(console)

    return root, blackboard, executor, input_provider, loader
