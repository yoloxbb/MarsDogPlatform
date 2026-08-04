"""Interactive demo for the bionic dog behavior tree.

Run with:
    uv run python -m bionic_dog_bt.demo

Commands:
    owner_call  - Inject respond_owner_call
    touch_head  - Inject respond_touch_head
    danger      - Inject avoid_danger
    emergency   - Inject emergency_stop
    hunger      - Inject seek_food_or_water
    clean       - Inject clean_self
    social      - Inject seek_social_interaction
    happy       - Inject express_happy
    fear        - Inject express_fear
    curious     - Inject express_curiosity
    explore     - Inject explore_environment
    excretion   - Inject excretion_request
    sleep       - Inject sleep_request
    idle        - Inject idle_look_around
    event       - Inject an EVT_VOICE_* event
    tick        - Advance one tick
    auto        - Run auto ticks until idle settles
    status      - Show current state
    quit        - Exit
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path for direct execution
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from bionic_dog_bt.tree_builder import create_runtime
from bionic_dog_bt.behavior_tree_node import Status
from bionic_dog_bt.constants import STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILURE, EMOTION_BEHAVIOR_MAP


def _print_state(blackboard, tree_status, console):
    """Print current blackboard state in a nicely formatted table."""
    table = Table(title="Behavior Tree State", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")

    # Active behavior
    ab = blackboard.active_behavior
    table.add_row("active_behavior",
                  f"{ab.behavior_name} (Lv{ab.priority_level}, val={ab.value:.0f})" if ab else "None")

    # Current behavior
    cb = blackboard.current_behavior
    table.add_row("current_behavior",
                  f"{cb.behavior_name} (Lv{cb.priority_level}, val={cb.value:.0f})" if cb else "None")

    table.add_row("current_status", blackboard.current_status)
    table.add_row("current_goal_id", str(blackboard.current_goal_id) if blackboard.current_goal_id else "None")

    # Tree status
    status_color = "green" if tree_status == Status.SUCCESS else ("yellow" if tree_status == Status.RUNNING else "red")
    table.add_row("tree_status", f"[{status_color}]{tree_status.value}[/{status_color}]")

    # Executor feedback
    fb = blackboard.executor_feedback
    if fb:
        table.add_row("executor.status", fb.status)
        table.add_row("executor.progress", f"{fb.progress:.1%}")
        table.add_row("executor.safe_to_interrupt", str(fb.safe_to_interrupt))
        table.add_row("executor.message", fb.message)
    else:
        table.add_row("executor_feedback", "None")

    # ── Need States (ROS2 /internal_need/state) ──────────────────────────────
    all_needs = blackboard.need_module.get_all_needs()
    if all_needs:
        for name, state in sorted(all_needs.items()):
            level_color = {
                "NORMAL": "dim",
                "TRIGGERED": "yellow",
                "URGENT": "bold magenta",
                "OVERFLOW": "bold red",
            }
            lc = level_color.get(state.level, "dim")
            table.add_row(
                f"need.{name}",
                f"[{lc}]val={state.current_value:.1f} level={state.level}[/{lc}] "
                f"(trigger={state.trigger_operator} {state.trigger_threshold:.0f}, "
                f"urgent={state.urgent_operator or '-'} "
                f"{state.urgent_threshold if state.urgent_threshold is not None else '-'}, "
                f"overflow={state.overflow_operator or '-'} "
                f"{state.overflow_threshold if state.overflow_threshold is not None else '-'})"
            )
    else:
        table.add_row("need_states", "(none active)")

    # ── Emotion States (ROS2 /emotion/state) ─────────────────────────────────
    all_emotions = blackboard.emotion_module.get_all_emotions()
    if all_emotions:
        for name, state in sorted(all_emotions.items()):
            trigger_mark = (
                " [bold green]TRIGGERED[/bold green]"
                if blackboard.emotion_module.is_triggered(name)
                else ""
            )
            table.add_row(
                f"emotion.{name}",
                f"val={state.current_value:.1f} / thr={state.trigger_threshold:.0f}"
                f"{trigger_mark}"
            )
    else:
        table.add_row("emotion_states", "(none active)")

    # Preemption
    table.add_row("preemption_occurred", str(blackboard.preemption_occurred))
    if blackboard.preemption_detail:
        table.add_row("preemption_detail", blackboard.preemption_detail)

    # Timeout
    table.add_row("timeout_occurred", str(blackboard.timeout_occurred))

    # Cooldown
    if blackboard.cooldown_until:
        cooldown_str = ", ".join(
            f"{k}: {v:.1f}" for k, v in blackboard.cooldown_until.items()
        )
        table.add_row("cooldown_until", cooldown_str)
    else:
        table.add_row("cooldown_until", "{}")

    # Last feedback event
    lfe = blackboard.last_feedback_event
    if lfe:
        table.add_row("last_feedback_event",
                      f"{lfe.behavior_name} → {lfe.status} ({lfe.reason})")
    else:
        table.add_row("last_feedback_event", "None")

    # Tick info
    table.add_row("tick_count", str(blackboard.tick_count))

    console.print(table)


def main():
    console = Console()

    # Resolve config path
    config_path = str(_PROJECT_ROOT / "config" / "behaviors.yaml")

    # Create runtime
    root, blackboard, executor, input_provider, loader = create_runtime(
        config_path=config_path, console=console
    )

    console.print(Panel.fit(
        "[bold cyan]Bionic Dog Behavior Tree Demo[/bold cyan]\n\n"
        "Commands: owner_call | touch_head | danger | emergency | hunger | clean\n"
        "          social | happy | fear | curious | explore | excretion | sleep\n"
        "          idle | tick | auto | status\n"
        "          event <EVENT_TYPE> [value] — inject an exact event_type\n"
        "          person on|off       — toggle person presence for check_person\n"
        "          emotion <name> <val> — set emotion value\n"
        "          quit",
        title="Welcome"
    ))

    # Command dispatch
    commands = {
        "owner_call": lambda: input_provider.inject_owner_call(85),
        "touch_head": lambda: input_provider.inject_touch_head(70),
        "danger": lambda: input_provider.inject_danger(100),
        "emergency": lambda: input_provider.inject_emergency_stop(100),
        "hunger": lambda: input_provider.inject_hunger(85),
        "clean": lambda: input_provider.inject_cleanliness(60),
        "social": lambda: input_provider.inject_social_need(75),
        "happy": lambda: input_provider.inject_joy_trigger(30),
        "fear": lambda: input_provider.inject_fear(80),
        "curious": lambda: input_provider.inject_curiosity(70),
        "explore": lambda: input_provider.inject_explore(60),
        "excretion": lambda: input_provider.inject_excretion(95),
        "sleep": lambda: input_provider.inject_sleep(90),
        "idle": lambda: input_provider.inject_idle(),
    }

    while True:
        try:
            cmd = console.input("\n[bold green]> [/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting...[/dim]")
            break

        if cmd == "quit":
            console.print("[dim]Goodbye![/dim]")
            break
        elif cmd == "status":
            # Don't tick, just show state
            _print_state(blackboard, root.status, console)
            continue
        elif cmd == "auto":
            console.print("[dim]Running auto ticks...[/dim]")
            for _ in range(30):
                # If no active behavior, inject idle
                if blackboard.active_behavior is None:
                    # Select from provider (will generate idle if empty)
                    candidate = input_provider.select()
                    if candidate:
                        blackboard.set_active_behavior(candidate)

                # Tick tree (this resets the selector each time since memory=False)
                root.reset()
                tree_status = root.tick()
                blackboard.tick_count += 1
                blackboard.last_tick_time = __import__("time").time()

                if blackboard.preemption_occurred:
                    console.print(f"[yellow]⚡ PREEMPT: {blackboard.preemption_detail}[/yellow]")

                # Small pause for simulation time
                __import__("time").sleep(0.1)
            _print_state(blackboard, tree_status, console)
            continue
        elif cmd == "tick":
            # Select candidate from provider (will generate idle if empty)
            candidate = input_provider.select()
            if candidate:
                blackboard.set_active_behavior(candidate)

        elif cmd in commands:
            # Inject the behavior
            behavior = commands[cmd]()
            # Select best candidate
            candidate = input_provider.select()
            if candidate:
                blackboard.set_active_behavior(candidate)
        elif cmd.startswith("person"):
            parts = cmd.split()
            if len(parts) >= 2 and parts[1] == "on":
                blackboard.perception_client.set_person_present(True, identity="owner")
                console.print("[cyan]Person present: ON (identity=owner)[/cyan]")
            elif len(parts) >= 2 and parts[1] == "off":
                blackboard.perception_client.set_no_person()
                console.print("[cyan]Person present: OFF[/cyan]")
            else:
                pc = blackboard.perception_client
                console.print(f"Person present: {pc.is_person_present()}, "
                              f"identity={pc.check_person()['identity']}")
            continue
        elif cmd.startswith("event"):
            parts = cmd.split()
            if len(parts) >= 2:
                event_type = parts[1]
                try:
                    value = float(parts[2]) if len(parts) >= 3 else None
                except ValueError:
                    console.print("[red]Invalid event value[/red]")
                    continue
                behavior = input_provider.inject_event(event_type, value)
                if behavior:
                    console.print(
                        f"[cyan]Event {event_type} "
                        f"→ {behavior.behavior_name}[/cyan]"
                    )
                    candidate = input_provider.select()
                    if candidate:
                        blackboard.set_active_behavior(candidate)
                else:
                    console.print(f"[red]Unknown event: {event_type}[/red]")
                    console.print(
                        "[dim]Examples: EVT_VOICE_COMMAND_SIT, "
                        "NEED_SOCIAL_URGENT 71, "
                        "EMO_JOY_TRIGGERED 30[/dim]"
                    )
            continue
        elif cmd.startswith("emotion"):
            # Manually set an emotion: "emotion happy 90"
            parts = cmd.split()
            if len(parts) >= 3:
                em_name = parts[1]
                try:
                    em_val = float(parts[2])
                    blackboard.emotion_module.set_emotion(em_name, em_val)
                    console.print(f"[cyan]Set emotion '{em_name}' = {em_val:.0f}[/cyan]")
                except ValueError:
                    console.print("[red]Invalid value[/red]")
            else:
                # Show all emotions
                all_em = blackboard.emotion_module.get_all_emotions()
                if all_em:
                    for name, state in sorted(all_em.items()):
                        trigger_state = (
                            "TRIGGERED"
                            if blackboard.emotion_module.is_triggered(name)
                            else "not-triggered"
                        )
                        console.print(
                            f"  {name}: {state.current_value:.1f} / "
                            f"{state.trigger_threshold:.0f} [{trigger_state}]"
                        )
                else:
                    console.print("[dim]No active emotions[/dim]")
            continue
        else:
            console.print(f"[red]Unknown command: {cmd}[/red]")
            continue

        # Tick the tree
        root.reset()  # Memory=False selector: re-evaluate from Lv0 each tick
        tree_status = root.tick()
        blackboard.tick_count += 1
        blackboard.last_tick_time = __import__("time").time()

        # Print state
        _print_state(blackboard, tree_status, console)

        # Highlight events
        if blackboard.preemption_occurred:
            console.print(f"[yellow]⚡ PREEMPTION: {blackboard.preemption_detail}[/yellow]")
        if blackboard.timeout_occurred:
            console.print("[red]⏰ TIMEOUT[/red]")
        if blackboard.last_feedback_event:
            lfe = blackboard.last_feedback_event
            color = "green" if lfe.status == STATUS_SUCCESS else "red"
            console.print(f"[{color}]📋 RESULT: {lfe.behavior_name} → {lfe.status}[/{color}]")


if __name__ == "__main__":
    main()
