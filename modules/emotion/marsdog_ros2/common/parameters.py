"""ROS2 参数描述器的统一构造工具。"""

from __future__ import annotations

from marsdog_core.types import MAX_TIME_SCALE_VALUE, MIN_TIME_SCALE_VALUE

try:
    from rcl_interfaces.msg import IntegerRange, ParameterDescriptor
except ModuleNotFoundError:
    IntegerRange = None
    ParameterDescriptor = None


def ParameterDescriptorValue(description: str, readOnly: bool):
    """创建普通 ROS2 参数描述器。"""
    if ParameterDescriptor is None:
        return None
    return ParameterDescriptor(description=description, read_only=readOnly)


def ReadOnlyParameterDescriptorValue(description: str):
    """创建启动后不可动态修改的参数描述器。"""
    return ParameterDescriptorValue(description, True)


def ReadOnlyIntegerParameterDescriptorValue(
    description: str,
    minimumValue: int,
    maximumValue: int,
):
    """创建带闭区间约束的只读整数参数描述器。"""
    if ParameterDescriptor is None or IntegerRange is None:
        return None
    return ParameterDescriptor(
        description=description,
        read_only=True,
        integer_range=[
            IntegerRange(
                from_value=minimumValue,
                to_value=maximumValue,
                step=1,
            )
        ],
    )


def TimeScaleParameterDescriptorValue(readOnly: bool):
    """创建限制为 1-100 整数的时间倍率参数描述器。"""
    if ParameterDescriptor is None or IntegerRange is None:
        return None
    return ParameterDescriptor(
        description="Virtual time scale: integer from 1 to 100",
        read_only=readOnly,
        integer_range=[
            IntegerRange(
                from_value=MIN_TIME_SCALE_VALUE,
                to_value=MAX_TIME_SCALE_VALUE,
                step=1,
            )
        ],
    )
