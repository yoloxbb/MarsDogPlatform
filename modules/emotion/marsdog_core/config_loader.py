"""配置加载工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


def LoadConfig(configName: str, configDir: str | Path | None = None) -> dict[str, Any]:
    """加载指定配置文件。"""
    configPath = _GetConfigPath(configName, configDir)
    text = configPath.read_text(encoding="utf-8")
    if configPath.suffix in {".yaml", ".yml"}:
        return _LoadYamlCompatibleText(text)
    return json.loads(text)


def LoadAllConfigs(configDir: str | Path | None = None) -> dict[str, Any]:
    """加载核心引擎需要的所有配置。"""
    demandConfig = LoadConfig("demands", configDir)
    return {
        "demands": demandConfig.get("demands", {}),
        "demandGlobalRules": demandConfig.get("globalRules", {}),
        "emotions": LoadConfig("emotions", configDir).get("emotions", {}),
        "personalityProfiles": LoadConfig("personality", configDir).get("profiles", {}),
        "priorities": LoadConfig("priorities", configDir).get("priorities", {}),
        "actions": LoadConfig("actions", configDir).get("actions", {}),
    }


def _GetConfigPath(configName: str, configDir: str | Path | None) -> Path:
    """定位配置文件路径。"""
    baseDir = Path(configDir) if configDir is not None else DEFAULT_CONFIG_DIR
    candidate = Path(configName)
    if candidate.suffix:
        if candidate.is_absolute():
            return candidate
        return baseDir / candidate

    for suffix in (".yaml", ".yml", ".json"):
        path = baseDir / f"{configName}{suffix}"
        if path.exists():
            return path
    raise FileNotFoundError(f"Config not found: {configName}")


def _LoadYamlCompatibleText(text: str) -> dict[str, Any]:
    """优先用 PyYAML，未安装时读取 JSON 兼容 YAML。"""
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return json.loads(text)

    data = yaml.safe_load(text)
    return data or {}
