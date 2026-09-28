"""YAML loader for behavior specifications."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .datatypes import BehaviorSpec


class YAMLLoader:
    """Loads behavior specifications from a YAML configuration file."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path: Optional[Path] = None
        self._specs: dict[str, BehaviorSpec] = {}
        if config_path:
            self.load(config_path)

    def load(self, config_path: str) -> dict[str, BehaviorSpec]:
        """Load and parse the YAML config file. Returns a dict of name → BehaviorSpec."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Behavior config not found: {config_path}")

        self.config_path = path
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._specs = {}
        behaviors = raw.get("behaviors", {})
        for name, data in behaviors.items():
            spec = BehaviorSpec(
                name=name,
                priority_level=int(data.get("priority_level", 6)),
                base_priority=int(data.get("base_priority", 50)),
                interrupt_policy=str(data.get("interrupt_policy", "immediate")),
                timeout_sec=float(data.get("timeout_sec", 30.0)),
                cooldown_sec=float(data.get("cooldown_sec", 0.0)),
                action_sequence=list(data.get("action_sequence", [])),
                default_params=dict(data.get("default_params", {})),
                style_modifiers=dict(data.get("style_modifiers", {})),
            )
            self._specs[name] = spec

        return self._specs

    def get_spec(self, name: str) -> Optional[BehaviorSpec]:
        """Get a behavior spec by name."""
        return self._specs.get(name)

    def get_all_specs(self) -> dict[str, BehaviorSpec]:
        """Get all loaded behavior specs."""
        return dict(self._specs)
