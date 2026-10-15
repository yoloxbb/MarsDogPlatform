"""Validation for additive expression presets; no aliases or controller implementations."""
from __future__ import annotations

import math


def read_presets_yaml(stream):
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in seen:
                    raise ValueError(f"duplicate preset YAML key {key!r}")
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    return yaml.load(stream, Loader=UniqueLoader)


def validate_presets(presets, reviewed, catalog):
    """Require an explicit, bounded expression plan with abort-on-failure stages."""
    errors = []
    for name, plan in presets.items():
        label = f"Preset {name!r}"
        if name in reviewed:
            errors.append(f"{label}: cannot override a reviewed behavior")
        if not isinstance(plan, dict):
            errors.append(f"{label}: expected mapping")
            continue
        if not isinstance(name, str) or plan.get('behavior_name') != name:
            errors.append(f"{label}: behavior key/name mismatch")
        if type(plan.get('preset_version')) is not int or plan['preset_version'] != 1:
            errors.append(f"{label}: unsupported preset_version")
        if plan.get('completion_scope') != 'expression_only':
            errors.append(f"{label}: completion_scope must be expression_only")
        if not isinstance(plan.get('description'), str) or not plan['description'].strip():
            errors.append(f"{label}: description is required")
        if plan.get('success_condition') != 'all_required_stages_completed':
            errors.append(f"{label}: all required stages must complete")
        budget = plan.get('runtime_budget_sec')
        valid_budget = (type(budget) in (int, float) and math.isfinite(budget) and 0 < budget <= 60)
        if not valid_budget:
            errors.append(f"{label}: runtime_budget_sec must be finite in (0, 60]")
        stages = plan.get('stages')
        if not isinstance(stages, list) or not stages:
            errors.append(f"{label}: nonempty stages required")
            continue
        total_budget = 0.0
        ids = set()
        for index, stage in enumerate(stages, 1):
            if not isinstance(stage, dict):
                errors.append(f"{label}: stage must be a mapping")
                continue
            sid = stage.get('stage_id')
            if not isinstance(sid, str) or not sid or sid in ids:
                errors.append(f"{label}: stage_id must be unique and nonempty")
            else:
                ids.add(sid)
            if type(stage.get('order')) is not int or stage['order'] != index:
                errors.append(f"{label}: stage order must match list order")
            if (stage.get('required') is not True or stage.get('failure_policy') != 'abort'
                    or stage.get('selection_policy') != 'random_one' or 'loop_policy' in stage):
                errors.append(f"{label}: bounded required random_one stages with abort are required")
            candidates = stage.get('candidates')
            if not isinstance(candidates, list) or not candidates:
                errors.append(f"{label}: nonempty candidates required")
                continue
            durations = []
            for candidate in candidates:
                unit = candidate.get('unit_id') if isinstance(candidate, dict) else None
                if not isinstance(unit, str) or unit not in catalog:
                    errors.append(f"{label}: unknown action {unit!r}")
                    continue
                duration = catalog[unit].get('timeout_sec')
                if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
                    errors.append(f"{label}: finite action budget required for {unit}")
                else:
                    durations.append(duration)
            total_budget += max(durations, default=0)
        if valid_budget and budget < total_budget + 2.0:
            errors.append(f"{label}: runtime budget must cover stages plus 2s orchestration margin")
    return errors
