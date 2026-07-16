"""ROS2 JSON 消息的虚拟时间上下文辅助函数。"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from marsdog_core.time_controller import MarsdogTimeController


def GetMessageWithTimeContextValue(
    payload: dict[str, Any],
    timeController: MarsdogTimeController,
    virtualDateTime: datetime | None = None,
) -> dict[str, Any]:
    """复制消息并附加统一 timeContext，保留原有顶层字段。"""
    result = dict(payload)
    wallTimestamp = result.get("timestamp")
    result["timeContext"] = timeController.GetTimeContextValue(
        virtualDateTime=virtualDateTime,
        wallTimestamp=float(wallTimestamp) if wallTimestamp is not None else None,
    )
    return result


def GetRandomGeneratorValue(randomSeed: object) -> random.Random | None:
    """根据 ROS2 参数创建可复现随机数生成器。"""
    if isinstance(randomSeed, bool):
        raise ValueError("random_seed must be -1 or a non-negative integer")
    if isinstance(randomSeed, int):
        seed = randomSeed
    elif isinstance(randomSeed, str) and re.fullmatch(r"-1|\d+", randomSeed.strip()):
        seed = int(randomSeed)
    else:
        raise ValueError("random_seed must be -1 or a non-negative integer")
    if seed < -1:
        raise ValueError("random_seed must be -1 or a non-negative integer")
    return None if seed == -1 else random.Random(seed)
