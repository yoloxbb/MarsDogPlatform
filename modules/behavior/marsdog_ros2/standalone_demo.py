"""Standalone demo — runs the full ROS2 pipeline without ROS2.

Starts behavior_tree_node + mock_action_executor_node in-process.
Interactive CLI to inject behavior signals and observe execution.

Run:
  uv run python -m marsdog_ros2.standalone_demo

Commands:
  hunger <val>      — inject Hunger need signal
  bladder <val>     — inject Bladder need signal
  social <val>      — inject Social need signal
  explore <val>     — inject Exploration need signal
  clean <val>       — inject Cleanliness need signal
  sleep <val>       — inject Sleepiness need signal
  emotion <name> <val> — set emotion (Joy/Excite/Fear/Anxiety/Curious/Calm)
  owner_call        — inject owner call event
  touch_head        — inject touch head event
  danger            — inject danger event
  emergency         — inject emergency stop
  cmd <CMD_XXX>     — inject voice command
  person on|off     — toggle person presence
  status            — show current state
  auto <n>          — run n auto ticks
  quit              — exit
"""

from __future__ import annotations

import sys
import time
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from bionic_dog_bt.constants import (
    PRIORITY_LEVELS, STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE,
    COMMAND_BEHAVIOR_MAP,
)

from marsdog_ros2.behavior_tree_node import BehaviorTreeNode
from marsdog_ros2.mock_action_executor_node import MockActionExecutorNode
from marsdog_ros2.interfaces import BehaviorSignal


# ═══════════════════════════════════════════════════════════════════════════════
# State display
# ═══════════════════════════════════════════════════════════════════════════════

def print_state(bt_node: BehaviorTreeNode, console: Console):
    bb = bt_node._blackboard
    table = Table(title="Behavior Tree Node State", header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")

    # BT state
    table.add_row("tick_count", str(bb.tick_count))
    table.add_row("current_behavior",
                  f"{bb.current_behavior.behavior_name} (Lv{bb.current_behavior.priority_level})"
                  if bb.current_behavior else "None")
    table.add_row("current_status", bb.current_status)
    table.add_row("current_goal_id", str(bb.current_goal_id) or "None")

    # Executor feedback
    fb = bb.executor_feedback
    if fb:
        table.add_row("progress", f"{fb.progress:.1%}")
        table.add_row("safe_to_interrupt", str(fb.safe_to_interrupt))
        table.add_row("message", fb.message)

    # Emotions
    for name, state in sorted(bb.emotion_module.get_all_emotions().items()):
        ov = " [bold red]OVF[/]" if bb.emotion_module.is_overflowing(name) else ""
        table.add_row(f"emotion.{name}",
                      f"{state.current_value:.0f}/100{ov} (decay={state.decay_rate:.0f}/s)")

    # Needs
    for name, state in sorted(bb.need_module.get_all_needs().items()):
        lc = {"NORMAL": "", "TRIGGERED": "[yellow]", "OVERFLOW": "[bold red]"}.get(state.level, "")
        table.add_row(f"need.{name}",
                      f"{lc}{state.current_value:.0f}/100 {state.level}[/]")

    # Preemption / timeout
    if bb.preemption_occurred:
        table.add_row("preemption", bb.preemption_detail)
    if bb.timeout_occurred:
        table.add_row("timeout", "[red]YES[/red]")

    # Last feedback
    lfe = bb.last_feedback_event
    if lfe:
        color = "green" if lfe.status == "SUCCESS" else "red"
        table.add_row("last_feedback",
                      f"[{color}]{lfe.behavior_name} → {lfe.status}[/{color}]")

    # Candidate pool
    with bt_node._lock:
        pool = list(bt_node._candidates)
    if pool:
        table.add_row("candidate_pool",
                      ", ".join(f"{s.behavior_name}(Lv{s.priority_level})" for s in pool[:5]))

    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    console = Console()

    # Start nodes
    bt_node = BehaviorTreeNode()
    action_node = MockActionExecutorNode()

    # Wire action executor into BT node
    bt_node._executor = None  # disable internal executor, use action node
    # The BT tick will call action_node directly for goal execution
    # (In ROS2 mode this would be an Action Client ↔ Server)

    # For mock mode, override BT's goal send to use action_node directly
    _original_send = bt_node._blackboard.__class__.start_behavior

    def _mock_start_behavior(bb, active, goal_id):
        bb.current_behavior = active
        bb.current_goal_id = goal_id
        bb.current_status = STATUS_RUNNING
        bb._behavior_start_time = time.time()
        bb._behavior_timeout = active.timeout_sec

        # Create goal and send to mock action executor
        goal = BehaviorSignal(
            behavior_id=active.behavior_id,
            behavior_name=active.behavior_name,
            priority_level=active.priority_level,
            value=active.value,
            need_type=active.need_type,
            params_json=json.dumps(active.params),
            timeout_sec=active.timeout_sec,
        )
        # Send to mock executor
        from marsdog_ros2.interfaces import ExecuteBehaviorGoal
        action_goal = ExecuteBehaviorGoal(
            behavior_id=goal.behavior_id,
            behavior_name=goal.behavior_name,
            priority_level=goal.priority_level,
            params_json=goal.params_json,
            timeout_sec=goal.timeout_sec,
        )
        action_node.send_goal(action_goal)
        bb.executor_feedback = action_node.get_feedback(action_goal.goal_id)

    # Monkey-patch blackboard so BT tick can access executor feedback
    import types
    bt_node._blackboard._action_node = action_node
    bt_node._blackboard._mock_start_behavior = _mock_start_behavior

    # Override BT's internal executor usage
    bt_node._use_action_node = True

    console.print(Panel.fit(
        "[bold cyan]MarsDog ROS2 Standalone Demo[/bold cyan]\n\n"
        "Behavior tree node + mock action executor running in-process.\n"
        "Commands:\n"
        "  hunger/bladder/social/explore/clean/sleep <val>\n"
        "  emotion <name> <val>   (Joy/Excite/Fear/Anxiety/Curious/Calm)\n"
        "  owner_call | touch_head | danger | emergency\n"
        "  cmd <CMD_XXX> | person on|off\n"
        "  status | auto <n> | quit",
        title="Welcome",
    ))

    # Command loop
    while True:
        try:
            cmd = console.input("\n[bold green]> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd == "quit":
            break
        elif cmd == "status":
            print_state(bt_node, console)
            continue
        elif cmd.startswith("auto"):
            parts = cmd.split()
            n = int(parts[1]) if len(parts) > 1 else 20
            for i in range(n):
                # Simulate one tick
                bt_node._on_tick()
                # Sync executor feedback
                if bt_node._blackboard.current_goal_id:
                    gid = bt_node._blackboard.current_goal_id
                    fb = action_node.get_feedback(gid)
                    if fb:
                        bt_node._blackboard.executor_feedback = \
                            type('FB', (), {
                                'behavior_id': fb.behavior_id,
                                'behavior_name': fb.behavior_name,
                                'status': fb.status,
                                'progress': fb.progress,
                                'safe_to_interrupt': fb.safe_to_interrupt,
                                'message': fb.message,
                            })()
                    result = action_node.get_result(gid)
                    if result:
                        bt_node._blackboard.current_status = result.status
                        from bionic_dog_bt.datatypes import BehaviorFeedbackEvent
                        bt_node._blackboard.last_feedback_event = BehaviorFeedbackEvent(
                            behavior_id=result.behavior_id,
                            behavior_name=result.behavior_name,
                            status=result.status,
                            result=result.result,
                            reason=result.reason,
                            reward=result.reward,
                            timestamp=time.time(),
                        )
                        action_node.remove_goal(gid)
                time.sleep(0.05)
            print_state(bt_node, console)
            continue
        elif cmd.startswith("emotion"):
            parts = cmd.split()
            if len(parts) >= 3:
                name, val = parts[1], float(parts[2])
                bt_node._blackboard.emotion_module.set_emotion(name, val)
                console.print(f"[cyan]Set {name} = {val:.0f}[/cyan]")
                # Generate emotion candidate
                bt_node.update_emotion_state({name: val})
            continue
        elif cmd.startswith("person"):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1] == "on":
                bt_node._blackboard.perception_client.set_person_present(True)
                console.print("[cyan]Person: ON[/cyan]")
            elif len(parts) >= 2 and parts[1] == "off":
                bt_node._blackboard.perception_client.set_no_person()
                console.print("[cyan]Person: OFF[/cyan]")
            continue
        elif cmd.startswith("cmd"):
            parts = cmd.split(maxsplit=1)
            if len(parts) >= 2:
                cid = parts[1].strip()
                bhv = COMMAND_BEHAVIOR_MAP.get(cid)
                if bhv:
                    signal = BehaviorSignal(
                        behavior_name=bhv,
                        priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
                        value=85.0,
                        need_type="external",
                        params_json=json.dumps({"command_id": cid, "source": "audio_command"}),
                    )
                    bt_node.add_signal(signal)
                    console.print(f"[cyan]Voice cmd {cid} → {bhv}[/cyan]")
                else:
                    console.print(f"[red]Unknown command: {cid}[/red]")
            continue

        # Need injections
        need_map = {
            "hunger": ("Hunger", "seek_food_or_water", "PHYSIO_NORMAL", "physiological"),
            "bladder": ("Bladder", "excretion_request", "PHYSIO_URGENT", "physiological_urgent"),
            "social": ("Social", "seek_social_interaction", "PSYCHOLOGICAL", "psychological"),
            "explore": ("Exploration", "explore_environment", "PSYCHOLOGICAL", "psychological"),
            "clean": ("Cleanliness", "clean_self", "PHYSIO_NORMAL", "physiological"),
            "sleep": ("Sleepiness", "sleep_request", "PHYSIO_URGENT", "physiological_urgent"),
        }

        parts = cmd.split()
        if parts[0] in need_map and len(parts) >= 2:
            need_name, bhv_name, level_key, need_type = need_map[parts[0]]
            val = float(parts[1])
            bt_node._blackboard.need_module.set_need(need_name, val)
            signal = BehaviorSignal(
                behavior_name=bhv_name,
                priority_level=PRIORITY_LEVELS[level_key],
                value=val,
                need_type=need_type,
            )
            bt_node.add_signal(signal)
            console.print(f"[cyan]Need {need_name}={val:.0f} → {bhv_name}[/cyan]")

        elif parts[0] == "owner_call":
            signal = BehaviorSignal(
                behavior_name="respond_owner_call",
                priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
                value=85.0, need_type="external",
            )
            bt_node.add_signal(signal)
        elif parts[0] == "touch_head":
            signal = BehaviorSignal(
                behavior_name="respond_touch_head",
                priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
                value=70.0, need_type="external",
            )
            bt_node.add_signal(signal)
        elif parts[0] == "danger":
            signal = BehaviorSignal(
                behavior_name="avoid_danger",
                priority_level=PRIORITY_LEVELS["SYSTEM"],
                value=100.0, need_type="survival",
            )
            bt_node.add_signal(signal)
        elif parts[0] == "emergency":
            signal = BehaviorSignal(
                behavior_name="emergency_stop",
                priority_level=PRIORITY_LEVELS["SYSTEM"],
                value=100.0, need_type="system",
            )
            bt_node.add_signal(signal)
        else:
            console.print(f"[red]Unknown: {cmd}[/red]")
            continue

        # Tick once after injection
        bt_node._on_tick()
        # Sync feedback
        if bt_node._blackboard.current_goal_id:
            gid = bt_node._blackboard.current_goal_id
            fb = action_node.get_feedback(gid)
            if fb:
                bt_node._blackboard.executor_feedback = \
                    type('FB', (), {
                        'behavior_id': fb.behavior_id,
                        'behavior_name': fb.behavior_name,
                        'status': fb.status,
                        'progress': fb.progress,
                        'safe_to_interrupt': fb.safe_to_interrupt,
                        'message': fb.message,
                    })()
        print_state(bt_node, console)

    # Cleanup
    bt_node.destroy_node()
    action_node.destroy_node()
    console.print("[dim]Shutdown complete.[/dim]")


if __name__ == "__main__":
    main()
