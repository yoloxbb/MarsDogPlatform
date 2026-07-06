"""性格参数计算系统入口。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .config_loader import LoadAllConfigs
from .personality_api import PersonalityAPI
from .state import MarsdogState


class MarsdogPersonalitySystem(PersonalityAPI):
    """只负责性格参数、预设和性格系数计算的系统。"""

    def __init__(
        self,
        configDir: str | Path | None = None,
        timeProvider: Callable[[], float] | None = None,
    ) -> None:
        """初始化性格计算系统。"""
        self.state = MarsdogState()
        self.configs = LoadAllConfigs(configDir)
        self._timeProvider = timeProvider or time.time
