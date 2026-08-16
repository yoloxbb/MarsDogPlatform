"""需求和情绪计算节点共用的时间参数声明。"""

from __future__ import annotations

from .parameters import ReadOnlyParameterDescriptorValue


def DeclareCalculationTimeParametersValue(node: object) -> None:
    """为计算节点声明只允许启动时设置的时间和随机种子参数。"""
    node.declare_parameter(
        "time_scale",
        1,
        descriptor=ReadOnlyParameterDescriptorValue(
            "Virtual time scale: integer from 1 to 100"
        ),
    )
    node.declare_parameter(
        "virtual_start_time",
        "auto",
        descriptor=ReadOnlyParameterDescriptorValue(
            "Virtual start time: auto or HH:MM"
        ),
    )
    node.declare_parameter(
        "random_seed",
        -1,
        descriptor=ReadOnlyParameterDescriptorValue(
            "Random seed: -1 or a non-negative integer"
        ),
    )
