"""Read and correlate normalized logs; ROS collection is optional and runtime-independent."""
import argparse
import json
import heapq
from pathlib import Path
import sys
from runtime_environment import ROOT

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40, "FATAL": 50, "CRITICAL": 50}
IDENTITIES = ("goal_id", "behavior_id", "candidate_id")


def sort_key(row):
    # UTC orders processes for presentation; monotonic time is only local evidence.
    return (row["timestamp"], row.get("monotonic_ns", 0), row["instance_id"], row["sequence"])


def iter_records(directory, errors):
    for path in sorted((Path(directory) / "structured").glob("*.jsonl*")):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                    strings = ("timestamp", "component", "instance_id", "level", "event_name")
                    if (not isinstance(row, dict) or row.get("log_schema_version") != 1
                            or any(not isinstance(row.get(k), str) for k in strings)
                            or not isinstance(row.get("fields"), dict)
                            or not isinstance(row.get("sequence"), int)
                            or not isinstance(row.get("monotonic_ns", 0), int)):
                        raise ValueError("unsupported log record")
                    yield row
                except ValueError:
                    # Diagnostics stay bounded even for a corrupt file.
                    if len(errors) < 1000:
                        errors.append({"file": str(path), "line": number,
                                       "reason": "malformed_or_incomplete_record"})


def read_records(directory):
    errors = []
    return sorted(iter_records(directory, errors), key=sort_key), errors


def value(row, key):
    result = row.get(key) or row.get("fields", {}).get(key)
    return result if isinstance(result, str) and result else None


def selector(rows, *, interaction=None, utterance=None, goal=None, component=None, level="DEBUG", event=None):
    # Typed keys avoid conflating a goal UUID with an unrelated candidate UUID.
    identities = {("goal_id", goal)} if goal else set()
    def seed(row):
        return bool(interaction or utterance) and (
            (not interaction or value(row, "interaction_id") == interaction)
            and (not utterance or value(row, "utterance_id") == utterance))
    if interaction or utterance:
        for row in rows:
            if seed(row):
                identities.update((k, value(row, k)) for k in IDENTITIES if value(row, k))
    def matches(row):
        # Explicitly different session identities take precedence over inferred links.
        if any(want and value(row, k) and value(row, k) != want
               for k, want in (("interaction_id", interaction), ("utterance_id", utterance))):
            return False
        correlated = seed(row) or any((k, value(row, k)) in identities for k in IDENTITIES)
        if (interaction or utterance or goal) and not correlated:
            return False
        owner = row.get("fields", {}).get("source_component", row.get("component"))
        return (not component or owner == component) and (
            LEVELS.get(row.get("level", ""), 0) >= LEVELS[level.upper()]) and (
            not event or row.get("event_name", "").startswith(event))
    return matches


def select_records(rows, **filters):
    matches = selector(rows, **filters)
    return [row for row in rows if matches(row)]


def query_records(directory, limit=100, **filters):
    # At most two file passes; retain only matching identities and the last N rows.
    errors = []
    matches = selector(iter_records(directory, []), **filters)
    selected = heapq.nlargest(limit, (r for r in iter_records(directory, errors) if matches(r)), key=sort_key)
    return sorted(selected, key=sort_key), errors


def read_health(directory):
    result = []
    for path in sorted((Path(directory) / "structured").glob("*.health.json")):
        try:
            result.append(json.loads(path.read_text()))
        except ValueError:
            result.append({"path": str(path), "error": "unreadable_health"})
    return result


def resolve_run(value):
    if value == "latest":
        return Path(json.loads((ROOT / "out/local/latest-run.json").read_text())["run_directory"])
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Run directory does not exist")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="latest")
    parser.add_argument("--interaction")
    parser.add_argument("--utterance")
    parser.add_argument("--goal")
    parser.add_argument("--component")
    parser.add_argument("--level", choices=tuple(k.lower() for k in LEVELS), default="debug")
    parser.add_argument("--event")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--prune", action="store_true", help="Plan cleanup of closed managed runs")
    parser.add_argument("--root", type=Path, default=ROOT / "out/local/runs")
    parser.add_argument("--keep-runs", type=int, default=20)
    parser.add_argument("--max-total-mb", type=int, default=1024)
    parser.add_argument("--apply", action="store_true", help="Apply the explicit retention plan")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.keep_runs < 0 or args.max_total_mb < 1:
        parser.error("limit / storage budget must be positive; keep-runs must be nonnegative")
    if args.apply and not args.prune:
        parser.error("--apply requires --prune")
    try:
        if args.prune:
            from log_runs import retention_plan, apply_retention
            plan = retention_plan(args.root, args.keep_runs, args.max_total_mb*1024*1024)
            if args.apply:
                apply_retention(plan, args.root)
            print(json.dumps({"applied": args.apply, **plan}, ensure_ascii=False, indent=2))
            return 0
        directory = resolve_run(args.run)
        if args.health:
            print(json.dumps(read_health(directory), ensure_ascii=False, indent=2))
            return 0
        selected, errors = query_records(directory, limit=args.limit, interaction=args.interaction,
                                         utterance=args.utterance, goal=args.goal, component=args.component,
                                         level=args.level, event=args.event)
        for row in selected:
            if args.json:
                print(json.dumps(row, ensure_ascii=False))
            else:
                fields = row.get("fields", {})
                print(f'{row["timestamp"]} {row["level"]:7} {row["component"]:9} {row["event_name"]} '
                      + json.dumps({"goal_id": row.get("goal_id"), "message": row.get("message"),
                                    "reason": fields.get("reason"), "status": fields.get("status")}, ensure_ascii=False))
        if errors:
            print(json.dumps({"log_read_errors": errors}, ensure_ascii=False), file=sys.stderr)
        if not selected:
            print("No matching unified log records in " + str(directory), file=sys.stderr)
        return 1 if errors else 0
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
