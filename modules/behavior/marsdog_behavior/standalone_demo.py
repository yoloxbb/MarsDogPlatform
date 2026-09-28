"""Standalone demo — runs the full behavior tree pipeline without ROS2.

Starts behavior_tree_node with MockActionExecutor in-process.
Interactive CLI to inject behavior signals and observe execution.

Run:
  uv run python -m marsdog_behavior.standalone_demo

Commands:
  hunger/bladder/social/explore/clean/sleep/energy <val>
                     — derive and inject the exact need event
  emotion <name> <val> — set emotion (Joy/Excite/Fear/Anxiety/Curious/Calm)
  owner_call        — inject owner call event
  touch_head        — inject touch head event
  danger            — inject danger event
  emergency         — inject emergency stop
  event <EVENT_TYPE> [value] — inject exact event_type
  person on|off     — toggle person presence
  animal dog|cat|off — configure a visible animal
  object <label>|off — configure a visible object
  status            — show current state
  auto <n>          — run n auto ticks
  quit              — exit
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from bionic_dog_bt.constants import (
    DEFAULT_EMOTION_CONFIG,
    DEFAULT_NEED_CONFIG,
    EMOTION_EVENT_BEHAVIOR_MAP,
    NEED_EVENT_BEHAVIOR_MAP,
    PRIORITY_LEVELS,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_FAILURE,
)

from marsdog_behavior.ros_node import BehaviorTreeRosNode


def _default_event_value(event_type: str) -> float:
    if event_type.startswith("NEED_"):
        entry = NEED_EVENT_BEHAVIOR_MAP.get(event_type)
        if entry:
            level = event_type.rsplit("_", 1)[-1]
            threshold_key = {
                "TRIGGERED": "trigger_threshold",
                "URGENT": "urgent_threshold",
                "OVERFLOW": "overflow_threshold",
            }[level]
            return (
                float(DEFAULT_NEED_CONFIG[entry["need_name"]][threshold_key])
                + 1.0
            )
        return 75.0
    if event_type.startswith("EMO_"):
        entry = EMOTION_EVENT_BEHAVIOR_MAP.get(event_type)
        if entry:
            return DEFAULT_EMOTION_CONFIG[
                entry["emotion_name"]
            ]["trigger_threshold"]
        return 50.0
    return 85.0


def _inject_exact_event(
    bt_node: BehaviorTreeRosNode,
    event_type: str,
    value: float,
):
    """Inject an exact configured event into the standalone runtime."""
    if event_type in NEED_EVENT_BEHAVIOR_MAP:
        entry = NEED_EVENT_BEHAVIOR_MAP[event_type]
        need_name = entry["need_name"]
        bt_node.blackboard.need_module.set_need(need_name, value)
        expected_level = event_type.rsplit("_", 1)[-1]
        if bt_node.blackboard.need_module.get_level(need_name) != expected_level:
            return None
        context = None
        if need_name == "Hunger":
            resolved = []
            bt_node.perception.request_hunger_context(resolved.append)
            context = resolved[0] if resolved else None
        elif need_name == "Social":
            resolved = []
            bt_node.perception.request_social_target(resolved.append)
            context = resolved[0] if resolved else None
            if context is None:
                return None
        elif need_name == "Exploration":
            resolved = []
            bt_node.perception.request_exploration_context(resolved.append)
            context = resolved[0] if resolved else None
        candidate = bt_node._intent_mapper.map_need_event(
            event_type,
            {
                "demand": need_name,
                "value": value,
                "level": expected_level,
                "visual_route": context.get("route") if context else None,
                "target": context.get("target") if context else None,
            },
        )
    elif event_type in EMOTION_EVENT_BEHAVIOR_MAP:
        entry = EMOTION_EVENT_BEHAVIOR_MAP[event_type]
        emotion_name = entry["emotion_name"]
        bt_node.blackboard.emotion_module.update_state(
            emotion_name,
            value,
            True,
        )
        resolved = []
        bt_node.perception.request_emotion_context(resolved.append)
        context = (
            resolved[0]
            if resolved
            else {"route": "solo", "target": None}
        )
        candidate = bt_node._intent_mapper.map_emotion_event(
            event_type,
            {"value": value, "visual_route": context["route"]},
            interactive=context["route"] == "human",
            target=context.get("target"),
            visual_route=context["route"],
        )
    else:
        candidate = bt_node._intent_mapper.map_audio_event(
            event_type,
            {"event_type": event_type, "intent_confidence": 0.95},
        )

    if candidate is not None:
        bt_node._add_candidate(candidate)
    return candidate


def _emotion_event_for_value(emotion_name: str, value: float) -> str | None:
    config = DEFAULT_EMOTION_CONFIG.get(emotion_name)
    if config is None or value < config["trigger_threshold"]:
        return None
    return f"EMO_{emotion_name.upper()}_TRIGGERED"


# ═══════════════════════════════════════════════════════════════════════════════
# State display
# ═══════════════════════════════════════════════════════════════════════════════

def print_state(bt_node: BehaviorTreeRosNode, console: Console):
    bb = bt_node.blackboard
    table = Table(title="Behavior Tree Node State", header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")

    table.add_row("tick_count", str(bb.tick_count))
    table.add_row("current_behavior",
                  f"{bb.current_behavior.behavior_name} (Lv{bb.current_behavior.priority_level})"
                  if bb.current_behavior else "None")
    table.add_row("current_status", bb.current_status)
    table.add_row("current_goal_id", str(bb.current_goal_id) or "None")

    fb = bb.executor_feedback
    if fb:
        table.add_row("progress", f"{fb.progress:.1%}")
        table.add_row("safe_to_interrupt", str(fb.safe_to_interrupt))
        table.add_row("message", fb.message)

    for name, state in sorted(bb.emotion_module.get_all_emotions().items()):
        triggered = (
            " [bold green]TRIGGERED[/]"
            if bb.emotion_module.is_triggered(name)
            else ""
        )
        table.add_row(f"emotion.{name}",
                      f"{state.current_value:.0f}/100{triggered} "
                      f"(threshold={state.trigger_threshold:.0f})")

    for name, state in sorted(bb.need_module.get_all_needs().items()):
        lc = {
            "NORMAL": "",
            "TRIGGERED": "[yellow]",
            "URGENT": "[bold magenta]",
            "OVERFLOW": "[bold red]",
        }.get(state.level, "")
        table.add_row(f"need.{name}",
                      f"{lc}{state.current_value:.0f}/100 {state.level}[/]")

    if bb.preemption_occurred:
        table.add_row("preemption", bb.preemption_detail)
    if bb.timeout_occurred:
        table.add_row("timeout", "[red]YES[/red]")

    lfe = bb.last_feedback_event
    if lfe:
        color = "green" if lfe.status == "SUCCESS" else "red"
        table.add_row("last_feedback",
                      f"[{color}]{lfe.behavior_name} → {lfe.status}[/{color}]")

    pool = bt_node.candidate_pool.candidates
    if pool:
        table.add_row("candidate_pool",
                      ", ".join(f"{s['behavior_name']}(Lv{s['priority_level']})" for s in pool[:5]))

    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    console = Console()

    bt_node = BehaviorTreeRosNode(force_mock=True)

    console.print(Panel.fit(
        "[bold cyan]MarsDog Behavior Standalone Demo[/bold cyan]\n\n"
        "Behavior tree node + MockActionExecutor running in-process.\n"
        "Commands:\n"
        "  hunger/bladder/social/explore/clean/sleep/energy <val>\n"
        "  emotion <name> <val>   (Joy/Excite/Fear/Anxiety/Curious/Calm)\n"
        "  owner_call | touch_head | danger | emergency\n"
        "  event <EVENT_TYPE> [value] | person on|off\n"
        "  animal dog|cat|off | object <label>|off\n"
        "  status | auto <n> | quit",
        title="Welcome",
    ))

    need_map = {
        "hunger": "Hunger",
        "bladder": "Bladder",
        "social": "Social",
        "explore": "Exploration",
        "clean": "Cleanliness",
        "sleep": "Sleepiness",
        "energy": "Energy",
    }

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
                bt_node._on_tick()
                time.sleep(0.05)
            print_state(bt_node, console)
            continue
        elif cmd.startswith("emotion"):
            parts = cmd.split()
            if len(parts) >= 3:
                name, val = parts[1], float(parts[2])
                event_type = _emotion_event_for_value(name, val)
                candidate = (
                    _inject_exact_event(bt_node, event_type, val)
                    if event_type
                    else None
                )
                if candidate:
                    console.print(
                        f"[cyan]{event_type} → {candidate.behavior_name}[/cyan]"
                    )
                else:
                    console.print(
                        f"[dim]{name}={val:.0f} is below its V2 threshold "
                        "or unsupported[/dim]"
                    )
            continue
        elif cmd.startswith("person"):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1] == "on":
                bt_node.perception.mock_set_person_present(True)
                console.print("[cyan]Person: ON[/cyan]")
            elif len(parts) >= 2 and parts[1] == "off":
                bt_node.perception.mock_set_no_person()
                console.print("[cyan]Person: OFF[/cyan]")
            continue
        elif cmd.startswith("animal"):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1] == "off":
                bt_node.perception.mock_set_animals([])
                console.print("[cyan]Animal: OFF[/cyan]")
            elif len(parts) >= 2 and parts[1] in ("cat", "dog"):
                bt_node.perception.mock_set_animals([parts[1]])
                console.print(f"[cyan]Animal: {parts[1]}[/cyan]")
            continue
        elif cmd.startswith("object"):
            parts = cmd.split(maxsplit=1)
            if len(parts) >= 2 and parts[1] == "off":
                bt_node.perception.mock_set_objects([])
                console.print("[cyan]Objects: OFF[/cyan]")
            elif len(parts) >= 2:
                bt_node.perception.mock_set_objects([{
                    "label": parts[1],
                    "confidence": 0.9,
                }])
                console.print(f"[cyan]Object: {parts[1]}[/cyan]")
            continue
        elif cmd.startswith("event"):
            parts = cmd.split()
            if len(parts) >= 2:
                event_type = parts[1]
                try:
                    value = (
                        float(parts[2])
                        if len(parts) >= 3
                        else _default_event_value(event_type)
                    )
                except ValueError:
                    console.print("[red]Invalid event value[/red]")
                    continue
                candidate = _inject_exact_event(bt_node, event_type, value)
                if candidate is None:
                    console.print(f"[red]Unknown event: {event_type}[/red]")
                else:
                    console.print(
                        f"[cyan]Event {event_type} "
                        f"→ {candidate.behavior_name}[/cyan]"
                    )
            continue

        # Need / event injections
        parts = cmd.split()
        if parts[0] in need_map and len(parts) >= 2:
            need_name = need_map[parts[0]]
            val = float(parts[1])
            bt_node.blackboard.need_module.set_need(need_name, val)
            level = bt_node.blackboard.need_module.get_level(need_name)
            if level == "NORMAL":
                console.print(
                    f"[dim]Need {need_name}={val:.0f} remains NORMAL[/dim]"
                )
                continue
            event_type = f"NEED_{need_name.upper()}_{level}"
            candidate = _inject_exact_event(bt_node, event_type, val)
            if candidate:
                console.print(
                    f"[cyan]{event_type} → {candidate.behavior_name}[/cyan]"
                )
        elif parts[0] == "owner_call":
            bt_node.add_signal(
                behavior_name="respond_owner_call",
                priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
                value=85.0, need_type="external",
            )
        elif parts[0] == "touch_head":
            bt_node.add_signal(
                behavior_name="respond_touch_head",
                priority_level=PRIORITY_LEVELS["EXTERNAL_INTERACTION"],
                value=70.0, need_type="external",
            )
        elif parts[0] == "danger":
            bt_node.add_signal(
                behavior_name="avoid_danger",
                priority_level=PRIORITY_LEVELS["SYSTEM"],
                value=100.0, need_type="survival",
            )
        elif parts[0] == "emergency":
            bt_node.add_signal(
                behavior_name="emergency_stop",
                priority_level=PRIORITY_LEVELS["SYSTEM"],
                value=100.0, need_type="system",
            )
        elif parts[0] not in (
            "status", "auto", "emotion", "person", "animal", "object",
            "event", "quit",
        ):
            console.print(f"[red]Unknown: {cmd}[/red]")
            continue

        bt_node._on_tick()
        print_state(bt_node, console)

    bt_node.destroy_node()
    console.print("[dim]Shutdown complete.[/dim]")


if __name__ == "__main__":
    main()
