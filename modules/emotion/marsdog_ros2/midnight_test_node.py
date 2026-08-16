"""在指定真实时长内离散推进虚拟凌晨场景的 ROS2 测试节点。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from marsdog_core import RealTimeTickScheduler
from marsdog_ros2.common.json_message import NormalizeJsonMessageValue
from marsdog_ros2.common.parameters import ReadOnlyParameterDescriptorValue
from marsdog_ros2.common.qos import (
    ReliableQoSValue,
    ReliableTransientLocalQoSValue,
)

try:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    ExternalShutdownException = None
    Node = object
    String = None


SCENARIO_NAME = "MIDNIGHT_00_06"
SCENARIO_VIRTUAL_SECONDS = 6 * 60 * 60
SCENARIO_STEP_SECONDS = 10 * 60
SCENARIO_STEP_COUNT = SCENARIO_VIRTUAL_SECONDS // SCENARIO_STEP_SECONDS
SCENARIO_COMPATIBILITY_SCALE = 24


class MidnightScenarioCompleted(Exception):
    """通知节点主循环场景已经完成并应正常退出。"""


def GetMidnightScenarioStartValue(
    referenceDateTime: datetime | None = None,
) -> datetime:
    """根据本地日期生成带时区的虚拟 00:00 起点。"""
    reference = referenceDateTime or datetime.now().astimezone()
    if reference.tzinfo is None:
        raise ValueError("referenceDateTime must include timezone information")
    return reference.replace(hour=0, minute=0, second=0, microsecond=0)


def GetMidnightScenarioStepDateTimeValue(
    virtualStartDateTime: datetime,
    stepSequence: int,
) -> datetime:
    """获取凌晨场景指定步骤对应的虚拟时间。"""
    if (
        not isinstance(virtualStartDateTime, datetime)
        or virtualStartDateTime.tzinfo is None
    ):
        raise ValueError("virtualStartDateTime must include timezone information")
    if isinstance(stepSequence, bool) or not isinstance(stepSequence, int):
        raise ValueError("stepSequence must be an integer")
    if stepSequence < 0 or stepSequence > SCENARIO_STEP_COUNT:
        raise ValueError("stepSequence is outside the midnight scenario")
    return virtualStartDateTime + timedelta(
        seconds=stepSequence * SCENARIO_STEP_SECONDS
    )


def BuildMidnightTestTimeStateValue(
    virtualStartDateTime: datetime,
    stepSequence: int,
    scenarioDurationSeconds: float,
    wallTimestamp: float,
) -> dict[str, Any]:
    """构造凌晨测试使用的统一时间状态消息。"""
    duration = float(scenarioDurationSeconds)
    if duration <= 0:
        raise ValueError("scenarioDurationSeconds must be greater than zero")
    virtualDateTime = GetMidnightScenarioStepDateTimeValue(
        virtualStartDateTime,
        stepSequence,
    )
    eventType = "TIME_INITIALIZED" if stepSequence == 0 else "TIME_TEST_STEP"
    elapsedSeconds = float(stepSequence * SCENARIO_STEP_SECONDS)
    return {
        "schema_version": "1.0",
        "timestamp": float(wallTimestamp),
        "event_type": eventType,
        "tickSequence": stepSequence,
        "testScenario": {
            "name": SCENARIO_NAME,
            "scenarioDurationSeconds": duration,
            "virtualStepSeconds": SCENARIO_STEP_SECONDS,
            "stepSequence": stepSequence,
            "stepCount": SCENARIO_STEP_COUNT,
            "effectiveTimeScale": SCENARIO_VIRTUAL_SECONDS / duration,
        },
        "timeContext": {
            "mode": "custom",
            # 测试场景通过 TIME_TEST_STEP 主动跳时，scale 保持生产协议上限。
            "scale": SCENARIO_COMPATIBILITY_SCALE,
            "revision": 0,
            "virtualStartDateTime": virtualStartDateTime.isoformat(),
            "virtualDateTime": virtualDateTime.isoformat(),
            "virtualTimestamp": virtualDateTime.timestamp(),
            "virtualElapsedSeconds": elapsedSeconds,
            "wallTimestamp": float(wallTimestamp),
        },
    }


class MidnightTestNode(Node):
    """发布离散测试时间并自动完成凌晨睡眠行为握手。"""

    def __init__(self) -> None:
        """初始化凌晨场景参数、Topic 和真实时间调度器。"""
        if rclpy is None or String is None:
            raise RuntimeError(
                "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
            )

        super().__init__("midnight_test_node")
        self._DeclareParameters()
        self.scenarioDurationSeconds = float(
            self.get_parameter("scenario_duration_seconds").value
        )
        self.completionHoldSeconds = float(
            self.get_parameter("completion_hold_seconds").value
        )
        self.autoStartSleep = bool(
            self.get_parameter("auto_start_sleep").value
        )
        if self.scenarioDurationSeconds <= 0:
            raise ValueError("scenario_duration_seconds must be greater than zero")
        if self.completionHoldSeconds < 0:
            raise ValueError("completion_hold_seconds must not be negative")

        self.virtualStartDateTime = GetMidnightScenarioStartValue()
        self.stepRealSeconds = (
            self.scenarioDurationSeconds / SCENARIO_STEP_COUNT
        )
        self.stepScheduler = RealTimeTickScheduler(
            time.monotonic(),
            self.stepRealSeconds,
        )
        self.stepSequence = 0
        self.autoSleepEventSent = False
        self.observedSleeping = False
        self.observedSleepDepths: set[str] = set()
        self.latestNeedState: dict[str, Any] = {}
        self.exitCode = 0
        self.scenarioCompleted = False
        self.completionTimer = None

        self.timeStatePublisher = self.create_publisher(
            String,
            "/simulation/time_state",
            ReliableTransientLocalQoSValue(1000),
        )
        self.behaviorResultPublisher = self.create_publisher(
            String,
            "/behavior/result_event",
            ReliableQoSValue(10),
        )
        self.resultPublisher = self.create_publisher(
            String,
            "/simulation/midnight_test_result",
            ReliableTransientLocalQoSValue(1),
        )
        self.create_subscription(
            String,
            "/internal_need/signal_event",
            self.OnNeedSignalMessage,
            ReliableQoSValue(10),
        )
        self.create_subscription(
            String,
            "/internal_need/state",
            self.OnNeedStateMessage,
            ReliableQoSValue(10),
        )
        self.scenarioTimer = self.create_timer(
            self.stepRealSeconds,
            self.OnScenarioTimer,
        )

        self.PublishTimeState(0)
        self.get_logger().info(
            "Midnight test started: virtual 00:00-06:00 in %.3f real seconds, "
            "%s steps, %.3f seconds per step"
            % (
                self.scenarioDurationSeconds,
                SCENARIO_STEP_COUNT,
                self.stepRealSeconds,
            )
        )

    def _DeclareParameters(self) -> None:
        """声明凌晨测试节点的只读启动参数。"""
        self.declare_parameter(
            "scenario_duration_seconds",
            30.0,
            descriptor=ReadOnlyParameterDescriptorValue(
                "Real seconds used to run virtual 00:00-06:00"
            ),
        )
        self.declare_parameter(
            "completion_hold_seconds",
            2.0,
            descriptor=ReadOnlyParameterDescriptorValue(
                "Real seconds to wait for final calculation state"
            ),
        )
        self.declare_parameter(
            "auto_start_sleep",
            True,
            descriptor=ReadOnlyParameterDescriptorValue(
                "Automatically publish ACTION_SLEEP STARTED"
            ),
        )

    def OnScenarioTimer(self) -> None:
        """按真实时间推进全部到期的虚拟10分钟步骤。"""
        if self.scenarioCompleted:
            return
        dueTickCount = self.stepScheduler.GetDueTickCountValue(time.monotonic())
        for _ in range(dueTickCount):
            if self.stepSequence >= SCENARIO_STEP_COUNT:
                break
            self.stepSequence += 1
            self.PublishTimeState(self.stepSequence)
            if self.stepSequence == SCENARIO_STEP_COUNT:
                self._BeginCompletionHold()
                break

    def PublishTimeState(self, stepSequence: int) -> None:
        """发布指定场景步骤的权威测试时间消息。"""
        payload = BuildMidnightTestTimeStateValue(
            self.virtualStartDateTime,
            stepSequence,
            self.scenarioDurationSeconds,
            time.time(),
        )
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.timeStatePublisher.publish(message)

    def OnNeedSignalMessage(self, message) -> None:
        """收到凌晨困倦触发信号后自动发送入睡开始结果。"""
        if not self.autoStartSleep or self.autoSleepEventSent:
            return
        payload = NormalizeJsonMessageValue(message)
        if payload.get("event_type") != "NEED_SLEEPINESS_TRIGGERED":
            return

        self.autoSleepEventSent = True
        resultPayload = {
            "schema_version": "1.0",
            "timestamp": time.time(),
            "event_id": "midnight-test-sleep-started",
            "action_type": "ACTION_SLEEP",
            "demand_type": "Sleepiness",
            "result_type": "STARTED",
            "metadata": {"source": "midnight_test_node"},
        }
        resultMessage = String()
        resultMessage.data = json.dumps(resultPayload, ensure_ascii=False)
        self.behaviorResultPublisher.publish(resultMessage)
        self.get_logger().info(
            "Sleepiness triggered; published ACTION_SLEEP + STARTED"
        )

    def OnNeedStateMessage(self, message) -> None:
        """记录场景期间最新需求状态和是否实际进入过睡眠。"""
        payload = NormalizeJsonMessageValue(message)
        if not payload:
            return
        self.latestNeedState = payload
        sleepState = payload.get("sleep", {})
        if isinstance(sleepState, dict) and bool(sleepState.get("isSleeping")):
            self.observedSleeping = True
            sleepDepth = str(sleepState.get("sleepDepth", ""))
            if sleepDepth:
                self.observedSleepDepths.add(sleepDepth)

    def _BeginCompletionHold(self) -> None:
        """到达06:00后等待最终需求状态发布。"""
        self.scenarioCompleted = True
        self.scenarioTimer.cancel()
        holdSeconds = max(0.05, self.completionHoldSeconds)
        self.completionTimer = self.create_timer(
            holdSeconds,
            self.OnCompletionHoldFinished,
        )
        self.get_logger().info(
            "Midnight test reached virtual 06:00; waiting %.3f seconds for final state"
            % holdSeconds
        )

    def OnCompletionHoldFinished(self) -> None:
        """校验最终睡眠状态、发布测试结果并准备退出。"""
        if self.completionTimer is not None:
            self.completionTimer.cancel()
        finalSleepState = self.latestNeedState.get("sleep", {})
        finalSleeping = (
            bool(finalSleepState.get("isSleeping"))
            if isinstance(finalSleepState, dict)
            else True
        )
        sleepStartPassed = (
            self.autoSleepEventSent
            if self.autoStartSleep
            else self.observedSleeping
        )
        sleepDepthPassed = {"Shallow", "Deep"}.issubset(
            self.observedSleepDepths
        )
        sleepFlowPassed = (
            sleepStartPassed
            and self.observedSleeping
            and sleepDepthPassed
            and not finalSleeping
        )
        stateReceived = bool(self.latestNeedState)
        passed = stateReceived and sleepFlowPassed
        self.exitCode = 0 if passed else 1

        resultPayload = {
            "schema_version": "1.0",
            "timestamp": time.time(),
            "event_type": "MIDNIGHT_TEST_COMPLETED",
            "status": "PASSED" if passed else "FAILED",
            "scenario": {
                "name": SCENARIO_NAME,
                "durationSeconds": self.scenarioDurationSeconds,
                "steps": self.stepSequence,
                "virtualStartTime": self.virtualStartDateTime.isoformat(),
                "virtualEndTime": GetMidnightScenarioStepDateTimeValue(
                    self.virtualStartDateTime,
                    self.stepSequence,
                ).isoformat(),
            },
            "checks": {
                "stateReceived": stateReceived,
                "autoSleepEventSent": self.autoSleepEventSent,
                "observedSleeping": self.observedSleeping,
                "observedSleepDepths": sorted(self.observedSleepDepths),
                "finalSleeping": finalSleeping,
            },
            "finalDemands": self.latestNeedState.get("demands", {}),
            "finalSleep": finalSleepState,
        }
        message = String()
        message.data = json.dumps(resultPayload, ensure_ascii=False)
        self.resultPublisher.publish(message)
        self.get_logger().info(
            "Midnight test %s: autoSleep=%s, sleepDepths=%s, finalSleeping=%s"
            % (
                resultPayload["status"],
                self.autoSleepEventSent,
                sorted(self.observedSleepDepths),
                finalSleeping,
            )
        )
        # 抛出专用异常退出 spin，避免在定时器回调内部调用 shutdown 形成等待。
        raise MidnightScenarioCompleted()


def main(args=None) -> int:
    """启动凌晨测试节点并返回场景验收状态码。"""
    if rclpy is None:
        raise RuntimeError(
            "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
        )

    rclpy.init(args=args)
    node = MidnightTestNode()
    try:
        rclpy.spin(node)
    except (
        KeyboardInterrupt,
        ExternalShutdownException,
        MidnightScenarioCompleted,
    ):
        pass
    finally:
        exitCode = node.exitCode
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exitCode


if __name__ == "__main__":
    raise SystemExit(main())
