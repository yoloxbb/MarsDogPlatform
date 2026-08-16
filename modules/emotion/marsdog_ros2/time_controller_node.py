"""ROS2 统一虚拟时间控制节点。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from math import isfinite

from marsdog_core import (
    MarsdogTimeController,
    RealTimeTickScheduler,
    VirtualTickScheduler,
)
from marsdog_core.types import NormalizeTimeScaleValue
from marsdog_ros2.common.parameters import (
    ParameterDescriptorValue,
    TimeScaleParameterDescriptorValue,
)
from marsdog_ros2.common.qos import ReliableTransientLocalQoSValue

try:
    import rclpy
    from rcl_interfaces.msg import SetParametersResult
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    SetParametersResult = None
    ExternalShutdownException = None
    Node = object
    String = None


MIDNIGHT_ACCELERATION_VIRTUAL_SECONDS = 6 * 60 * 60
MIDNIGHT_ACCELERATION_STEP_SECONDS = 10 * 60
MIDNIGHT_ACCELERATION_STEP_COUNT = (
    MIDNIGHT_ACCELERATION_VIRTUAL_SECONDS
    // MIDNIGHT_ACCELERATION_STEP_SECONDS
)


class TimeControllerNode(Node):
    """维护权威虚拟时钟并发布逐虚拟秒 Tick。"""

    def __init__(self) -> None:
        """初始化统一时间控制节点。"""
        if rclpy is None or String is None or SetParametersResult is None:
            raise RuntimeError(
                "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
            )

        super().__init__("time_controller_node")
        self._DeclareTimeParameters()
        self.timeController = MarsdogTimeController(
            self.get_parameter("time_scale").value,
            self.get_parameter("virtual_start_time").value,
        )
        self.midnightAccelerationEnabled = bool(
            self.get_parameter("midnight_acceleration_enabled").value
        )
        self.midnightDurationSeconds = float(
            self.get_parameter("midnight_duration_seconds").value
        )
        self._ValidateMidnightAccelerationParameters()
        self.tickScheduler = VirtualTickScheduler(
            self.timeController.GetVirtualStartDateTimeValue(),
            1.0,
        )
        self.tickSequence = 0
        self.timeTimer = None
        self.midnightAccelerationActive = False
        self.midnightAccelerationStart = None
        self.midnightAccelerationStepSequence = 0
        self.midnightStepScheduler = None
        self.statePublisher = self.create_publisher(
            String,
            "/simulation/time_state",
            ReliableTransientLocalQoSValue(1000),
        )
        self.add_on_set_parameters_callback(self.OnSetParameters)
        virtualStartDateTime = self.timeController.GetVirtualStartDateTimeValue()
        if self._IsExactMidnightValue(virtualStartDateTime):
            self._StartMidnightAcceleration(
                virtualStartDateTime,
                publishState=False,
            )
        self._ResetTimeTimer()
        self.PublishTimeState(
            "TIME_INITIALIZED",
            virtualStartDateTime,
        )
        self._LogCurrentScale("initialized")

    def OnSetParameters(self, parameters: list[object]):
        """校验并应用运行时整数倍率切换。"""
        requestedScale = None
        for parameter in parameters:
            if getattr(parameter, "name", "") == "time_scale":
                requestedScale = getattr(parameter, "value", None)

        if requestedScale is None:
            return SetParametersResult(successful=True)

        try:
            normalizedScale = NormalizeTimeScaleValue(requestedScale)
        except (TypeError, ValueError):
            return SetParametersResult(
                successful=False,
                reason="time_scale must be an integer between 1 and 100",
            )

        if normalizedScale == self.timeController.GetTimeScaleValue():
            return SetParametersResult(successful=True)

        # 先按当前模式消费已经到期的普通 Tick 或凌晨加速步骤。
        if self.midnightAccelerationActive:
            self.PublishDueMidnightAccelerationSteps()
        else:
            self.PublishDueTicks()
        self.timeController.SetTimeScaleValue(normalizedScale)
        if self.midnightAccelerationActive:
            # 加速期间以最近一个离散步骤为权威锚点，避免换倍率产生中间漂移。
            self.timeController.SetVirtualDateTimeValue(
                self._GetCurrentMidnightAccelerationDateTimeValue()
            )
        self._ResetTimeTimer()
        self.PublishTimeState(
            "TIME_MODE_CHANGED",
            self.timeController.GetVirtualDateTimeValue(),
        )
        self._LogCurrentScale("changed")
        return SetParametersResult(successful=True)

    def OnTimeTimer(self) -> None:
        """根据当前模式发布普通虚拟秒或凌晨加速步骤。"""
        if self.midnightAccelerationActive:
            self.PublishDueMidnightAccelerationSteps()
            return
        self.PublishDueTicks()

    def PublishDueTicks(self) -> None:
        """发布截至当前虚拟时间全部到期的逐秒 Tick。"""
        virtualNow = self.timeController.GetVirtualDateTimeValue()
        for tickDateTime in self.tickScheduler.GetDueTickDateTimesValue(virtualNow):
            self.tickSequence += 1
            self.PublishTimeState("TIME_TICK", tickDateTime)
            if self._IsExactMidnightValue(tickDateTime):
                self._StartMidnightAcceleration(
                    tickDateTime,
                    publishState=True,
                )
                break

    def PublishDueMidnightAccelerationSteps(self) -> None:
        """发布截至当前真实时间到期的虚拟10分钟凌晨步骤。"""
        if self.midnightStepScheduler is None:
            return
        dueStepCount = self.midnightStepScheduler.GetDueTickCountValue(
            time.monotonic()
        )
        for _ in range(dueStepCount):
            if (
                self.midnightAccelerationStepSequence
                >= MIDNIGHT_ACCELERATION_STEP_COUNT
            ):
                break
            self.midnightAccelerationStepSequence += 1
            virtualDateTime = self.midnightAccelerationStart + timedelta(
                seconds=(
                    self.midnightAccelerationStepSequence
                    * MIDNIGHT_ACCELERATION_STEP_SECONDS
                )
            )
            # 每一步重建24倍连续锚点，下一步再明确向前跳到新的权威时间。
            self.timeController.SetVirtualDateTimeValue(virtualDateTime)
            self.tickSequence += MIDNIGHT_ACCELERATION_STEP_SECONDS
            self.PublishTimeState(
                "TIME_ACCELERATED_STEP",
                virtualDateTime,
            )
            if (
                self.midnightAccelerationStepSequence
                == MIDNIGHT_ACCELERATION_STEP_COUNT
            ):
                self._FinishMidnightAcceleration(virtualDateTime)
                break

    def PublishTimeState(self, eventType: str, virtualDateTime: datetime) -> None:
        """发布权威时间状态或倍率变化事件。"""
        wallTimestamp = time.time()
        timeContext = self.timeController.GetTimeContextValue(
            virtualDateTime=virtualDateTime,
            wallTimestamp=wallTimestamp,
        )
        if self.midnightAccelerationEnabled:
            timeContext.update(self._GetMidnightAccelerationContextValue())
        payload = {
            "schema_version": "1.0",
            "timestamp": wallTimestamp,
            "event_type": eventType,
            "tickSequence": self.tickSequence,
            "timeContext": timeContext,
        }
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.statePublisher.publish(message)

    def _DeclareTimeParameters(self) -> None:
        """声明动态倍率参数和只读虚拟起点参数。"""
        self.declare_parameter(
            "time_scale",
            1,
            descriptor=TimeScaleParameterDescriptorValue(readOnly=False),
        )
        self.declare_parameter(
            "virtual_start_time",
            "auto",
            descriptor=ParameterDescriptorValue(
                "Virtual start time: auto or HH:MM",
                readOnly=True,
            ),
        )
        self.declare_parameter(
            "midnight_acceleration_enabled",
            False,
            descriptor=ParameterDescriptorValue(
                "Accelerate virtual 00:00-06:00 with discrete 10-minute steps",
                readOnly=True,
            ),
        )
        self.declare_parameter(
            "midnight_duration_seconds",
            30.0,
            descriptor=ParameterDescriptorValue(
                "Real seconds used for each virtual 00:00-06:00 window",
                readOnly=True,
            ),
        )

    def _ResetTimeTimer(self) -> None:
        """按当前倍率重建逐虚拟秒定时器。"""
        if self.timeTimer is not None:
            self.destroy_timer(self.timeTimer)
        self.timeTimer = self.create_timer(
            self.timeController.GetRealIntervalValue(1.0),
            self.OnTimeTimer,
        )

    def _ValidateMidnightAccelerationParameters(self) -> None:
        """校验任意基础倍率共用的凌晨加速时长。"""
        if (
            not isfinite(self.midnightDurationSeconds)
            or self.midnightDurationSeconds <= 0
        ):
            raise ValueError(
                "midnight_duration_seconds must be a finite positive number"
            )

    def _StartMidnightAcceleration(
        self,
        midnightDateTime: datetime,
        publishState: bool,
    ) -> None:
        """从当天00:00开始离散加速到06:00。"""
        if not self.midnightAccelerationEnabled:
            return
        self.timeController.SetVirtualDateTimeValue(midnightDateTime)
        self.midnightAccelerationActive = True
        self.midnightAccelerationStart = midnightDateTime
        self.midnightAccelerationStepSequence = 0
        self.midnightStepScheduler = RealTimeTickScheduler(
            time.monotonic(),
            self.midnightDurationSeconds / MIDNIGHT_ACCELERATION_STEP_COUNT,
        )
        if publishState:
            self.PublishTimeState(
                "TIME_ACCELERATION_CHANGED",
                midnightDateTime,
            )
        self.get_logger().info(
            "Midnight acceleration started: %s -> %s in %.3f real seconds"
            % (
                midnightDateTime.isoformat(),
                (midnightDateTime + timedelta(hours=6)).isoformat(),
                self.midnightDurationSeconds,
            )
        )

    def _FinishMidnightAcceleration(
        self,
        virtualDateTime: datetime,
    ) -> None:
        """在06:00结束凌晨加速并恢复当前基础倍率。"""
        self.midnightAccelerationActive = False
        self.midnightStepScheduler = None
        self.tickScheduler = VirtualTickScheduler(
            self.timeController.GetVirtualStartDateTimeValue(),
            1.0,
        )
        self.tickScheduler.AlignToDateTimeValue(virtualDateTime)
        self.PublishTimeState(
            "TIME_ACCELERATION_CHANGED",
            virtualDateTime,
        )
        self.get_logger().info(
            "Midnight acceleration finished at %s; resumed continuous %sx"
            % (
                virtualDateTime.isoformat(),
                self.timeController.GetTimeScaleValue(),
            )
        )

    def _GetCurrentMidnightAccelerationDateTimeValue(self) -> datetime:
        """获取当前凌晨离散步骤对应的权威虚拟时间。"""
        if self.midnightAccelerationStart is None:
            raise RuntimeError("midnight acceleration has not started")
        return self.midnightAccelerationStart + timedelta(
            seconds=(
                self.midnightAccelerationStepSequence
                * MIDNIGHT_ACCELERATION_STEP_SECONDS
            )
        )

    def _GetMidnightAccelerationContextValue(self) -> dict[str, object]:
        """构造基础倍率与当前有效倍率的加速上下文。"""
        effectiveScale = (
            MIDNIGHT_ACCELERATION_VIRTUAL_SECONDS
            / self.midnightDurationSeconds
            if self.midnightAccelerationActive
            else float(self.timeController.GetTimeScaleValue())
        )
        return {
            "effectiveScale": effectiveScale,
            "midnightAcceleration": {
                "enabled": self.midnightAccelerationEnabled,
                "active": self.midnightAccelerationActive,
                "durationSeconds": self.midnightDurationSeconds,
                "virtualStepSeconds": MIDNIGHT_ACCELERATION_STEP_SECONDS,
                "stepSequence": self.midnightAccelerationStepSequence,
                "stepCount": MIDNIGHT_ACCELERATION_STEP_COUNT,
            },
        }

    def _IsExactMidnightValue(self, virtualDateTime: datetime) -> bool:
        """判断虚拟时间是否正好位于当天00:00:00。"""
        return (
            virtualDateTime.hour == 0
            and virtualDateTime.minute == 0
            and virtualDateTime.second == 0
            and virtualDateTime.microsecond == 0
        )

    def _LogCurrentScale(self, operation: str) -> None:
        """记录当前时间倍率和连续虚拟时间。"""
        self.get_logger().info(
            "Time scale %s: %sx, virtual time: %s, revision: %s"
            % (
                operation,
                self.timeController.GetTimeScaleValue(),
                self.timeController.GetVirtualDateTimeValue().isoformat(),
                self.timeController.GetTimeRevisionValue(),
            )
        )


def main(args=None) -> None:
    """启动统一虚拟时间控制节点。"""
    if rclpy is None:
        raise RuntimeError(
            "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
        )

    rclpy.init(args=args)
    node = TimeControllerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
