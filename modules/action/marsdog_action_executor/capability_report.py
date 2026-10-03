"""Read-only capability evidence from Action's own loader and Lite3 policy."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from .config_loader import ConfigLoader
from .adapters.lite3_backend import Lite3ChassisBackend


def report(config_dir=None, *, chassis="lite3", runtime=None):
    runtime = dict(runtime or {})
    supported = {"lite3_enabled", "go2_enabled", "lite3_allow_proxies",
                 "lite3_allow_unverified", "navigation_enabled"}
    if set(runtime) - supported or any(type(value) is not bool for value in runtime.values()):
        raise ValueError("Only explicit boolean runtime capability overrides are accepted")
    config = ConfigLoader(config_dir)
    config.load_all()
    lite3 = config.lite3_action_config
    plans = config.get_lite3_action_plans()
    def forbidden_publish(_):
        raise AssertionError("Capability inspection must never publish")
    backend = Lite3ChassisBackend(
        forbidden_publish, forbidden_publish, plans,
        allow_proxies=runtime.get("lite3_allow_proxies", lite3.get("allow_proxies", False)),
        allow_unverified=runtime.get("lite3_allow_unverified", lite3.get("allow_unverified", False)),
        accepted_unverified_actions=lite3.get("accepted_unverified_actions", []))
    routes = config.get_controller_routes(chassis)
    units = {}
    for unit_id in sorted(config.action_catalog):
        route = routes.get(unit_id, routes.get("_default", "unsupported"))
        item = {"route": route, "configuration_status": "runtime_check_required",
                "reason": "Adapter readiness, target, posture and safety require runtime evidence",
                "hardware_acceptance": "unknown"}
        if route == "unsupported":
            item.update(configuration_status="blocked", reason="unsupported_controller_route")
        elif route == "mock":
            item.update(configuration_status="simulated_only", reason="mock_route")
        elif route == "lite3":
            allowed = backend.can_execute(unit_id)
            item.update(policy_allowed=allowed,
                        declared_verified=bool(plans.get(unit_id, {}).get("verified", False)),
                        fidelity=plans.get(unit_id, {}).get("fidelity"),
                        plan_id=plans.get(unit_id, {}).get("plan_id"))
            if not runtime.get("lite3_enabled", lite3.get("enabled", False)):
                item.update(configuration_status="blocked", reason="lite3_backend_disabled")
            elif not allowed:
                item.update(configuration_status="blocked", reason="lite3_policy_gated")
        elif route == "go2" and not runtime.get("go2_enabled", config.go2_sport_config.get("enabled", False)):
            item.update(configuration_status="blocked", reason="go2_backend_disabled")
        elif route == "behavior_mobility" and not runtime.get("navigation_enabled", config.navigation_config.get("enabled", False)):
            item.update(configuration_status="blocked", reason="navigation_disabled")
        units[unit_id] = item
    behaviors = {}
    for name, template in sorted(config.get_all_behavior_templates().items()):
        stages = []
        for stage in template.get("stages", []):
            candidates = [x if isinstance(x, str) else x["unit_id"] for x in stage["candidates"]]
            states = [units[unit]["configuration_status"] for unit in candidates]
            stages.append({"stage_id": stage["stage_id"], "required": stage.get("required", True),
                           "units": candidates, "all_candidates_blocked": all(s == "blocked" for s in states),
                           "some_candidates_blocked": any(s == "blocked" for s in states),
                           "conditions_require_runtime": True})
        blocked = any(s["required"] and s["all_candidates_blocked"] for s in stages)
        behaviors[name] = {"configuration_status": "blocked" if blocked else "runtime_check_required",
                           "stages": stages, "hardware_acceptance": "unknown"}
    folder = config.config_dir
    return {"schema_version": 1, "chassis": chassis, "runtime_overrides": runtime,
            "config_dir": str(folder), "module_file": __file__,
            "config_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(folder.glob("*.yaml"))},
            "units": units, "behaviors": behaviors,
            "scope": "Read-only configuration/policy evidence; no ROS, motion, sensors or live readiness. "
                     "declared_verified is configuration metadata, not this run's hardware acceptance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--chassis", choices=("lite3", "go2"), default="lite3")
    parser.add_argument("--runtime-json", type=Path)
    args = parser.parse_args()
    runtime = json.loads(args.runtime_json.read_text()) if args.runtime_json else {}
    print(json.dumps(report(args.config_dir, chassis=args.chassis, runtime=runtime),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
