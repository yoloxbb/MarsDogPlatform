"""把全迹 ONE1000 哨兵摸头检测转换为 Marsdog 触摸事件。"""

from __future__ import annotations

import copy
import json
import os
import termios
import time
from collections import deque
from math import isfinite
from typing import Any

from marsdog_core.one1000_protocol import (
    ONE1000_HEARTBEAT_TYPE,
    ONE1000_SENTRY_CLEAR_CACHE_COMMAND,
    ONE1000_SENTRY_CONTROL_TYPE,
    ONE1000_SENTRY_START_COMMAND,
    ONE1000_SENTRY_STATUS_TYPE,
    ONE1000_SENTRY_STOP_COMMAND,
    ONE1000_TOUCH_THRESHOLD_TYPE,
    BuildOne1000CommandValue,
    BuildOne1000TouchThresholdValue,
    One1000HeadPetEdgeDetector,
    One1000Heartbeat,
    One1000SentryStatus,
    One1000StreamParser,
    One1000TLV,
    ParseOne1000DeviceResponseValue,
    ParseOne1000HeartbeatValue,
    ParseOne1000SentryStatusValue,
)

try:
    import rclpy
    from rcl_interfaces.msg import IntegerRange, ParameterDescriptor
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
except ModuleNotFoundError:
    rclpy = None
    IntegerRange = None
    ParameterDescriptor = None
    ExternalShutdownException = None
    Node = object
    QoSProfile = None
    ReliabilityPolicy = None
    HistoryPolicy = None
    String = None


DEFAULT_ONE1000_SERIAL_PORT = "/dev/ttyUSB1"
ONE1000_SERIAL_BAUD_RATE = 115200
ONE1000_HEARTBEAT_TIMEOUT_SECONDS = 2.5


class One1000SerialPort:
    """使用 Python 标准库管理 ONE1000 非阻塞串口。"""

    def __init__(self, devicePath: str) -> None:
        """打开串口并保存原始终端配置，便于退出时恢复。"""
        if not isinstance(devicePath, str) or not devicePath.strip():
            raise ValueError("ONE1000 serial port must be a non-empty path")
        self.devicePath = devicePath.strip()
        self._fileDescriptor: int | None = None
        self._originalAttributes: list[Any] | None = None
        self.OpenValue()

    def OpenValue(self) -> None:
        """以 115200 8N1、原始模式、非阻塞方式打开设备。"""
        if self._fileDescriptor is not None:
            return
        fileDescriptor = os.open(
            self.devicePath,
            os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK,
        )
        try:
            originalAttributes = termios.tcgetattr(fileDescriptor)
            attributes = copy.deepcopy(originalAttributes)
            attributes[0] = 0
            attributes[1] = 0
            attributes[2] &= ~(
                termios.PARENB
                | termios.CSTOPB
                | termios.CSIZE
                | getattr(termios, "CRTSCTS", 0)
            )
            attributes[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
            attributes[3] = 0
            attributes[4] = termios.B115200
            attributes[5] = termios.B115200
            attributes[6][termios.VMIN] = 0
            attributes[6][termios.VTIME] = 0
            termios.tcsetattr(fileDescriptor, termios.TCSANOW, attributes)
            termios.tcflush(fileDescriptor, termios.TCIFLUSH)
        except Exception:
            os.close(fileDescriptor)
            raise
        self._fileDescriptor = fileDescriptor
        self._originalAttributes = copy.deepcopy(originalAttributes)

    def ReadAvailableValue(self, maxBytes: int = 4096) -> bytes:
        """读取当前可用字节；没有数据时返回空字节串。"""
        if self._fileDescriptor is None:
            return b""
        try:
            return os.read(self._fileDescriptor, maxBytes)
        except BlockingIOError:
            return b""

    def WriteValue(self, data: bytes | bytearray | memoryview) -> None:
        """向设备写入一个完整短命令包。"""
        if self._fileDescriptor is None:
            raise RuntimeError("ONE1000 serial port is closed")
        payload = bytes(data)
        writtenLength = os.write(self._fileDescriptor, payload)
        if writtenLength != len(payload):
            raise OSError(
                f"ONE1000 serial short write: {writtenLength}/{len(payload)}"
            )
        # 退出前也必须确保停止命令真正离开发送缓冲区。
        termios.tcdrain(self._fileDescriptor)

    def CloseValue(self) -> None:
        """恢复进入节点前的终端配置并关闭设备。"""
        if self._fileDescriptor is None:
            return
        fileDescriptor = self._fileDescriptor
        self._fileDescriptor = None
        try:
            if self._originalAttributes is not None:
                termios.tcsetattr(
                    fileDescriptor,
                    termios.TCSANOW,
                    self._originalAttributes,
                )
        finally:
            os.close(fileDescriptor)


def BuildOne1000TactileEventValue(
    sentryStatus: One1000SentryStatus,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """把有效摸头状态构造成 `/perception/tactile_event` V1 消息。"""
    if sentryStatus is None or not sentryStatus.headTouchDetected:
        raise ValueError("ONE1000 tactile event requires an active head touch")
    eventTimestamp = time.time() if timestamp is None else float(timestamp)
    if not isfinite(eventTimestamp):
        raise ValueError("ONE1000 tactile timestamp must be finite")
    return {
        "schema_version": "1.0",
        "timestamp": eventTimestamp,
        "event_type": "EVT_TACTILE_HEAD_PET",
        "source": "ONE1000",
        "sensorType": "UWB_RADAR",
        "touchState": "STARTED",
        "rawStatus": sentryStatus.rawStatus,
        "livingBodyDetected": sentryStatus.livingBodyDetected,
        "maxRadarValue": sentryStatus.maxRadarValue,
        "livingBodyFirstIndex": sentryStatus.livingBodyFirstIndex,
    }


def BuildOne1000StatusValue(
    serialPort: str,
    serialOpen: bool,
    heartbeat: One1000Heartbeat | None,
    heartbeatAgeSeconds: float | None,
    sentryStatus: One1000SentryStatus | None,
    sentryStatusAgeSeconds: float | None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """构造可按 1 Hz 发布的 ONE1000 硬件诊断状态。"""
    if not isinstance(serialPort, str) or not serialPort.strip():
        raise ValueError("ONE1000 status serial port must be a non-empty path")
    if not isinstance(serialOpen, bool):
        raise TypeError("ONE1000 status serialOpen must be boolean")
    eventTimestamp = time.time() if timestamp is None else float(timestamp)
    if not isfinite(eventTimestamp):
        raise ValueError("ONE1000 status timestamp must be finite")

    normalizedHeartbeatAge = _NormalizeOptionalAgeSecondsValue(
        heartbeatAgeSeconds,
        "heartbeat",
    )
    normalizedSentryAge = _NormalizeOptionalAgeSecondsValue(
        sentryStatusAgeSeconds,
        "sentry status",
    )
    if (heartbeat is None) != (normalizedHeartbeatAge is None):
        raise ValueError("ONE1000 heartbeat and age must be provided together")
    if (sentryStatus is None) != (normalizedSentryAge is None):
        raise ValueError("ONE1000 sentry status and age must be provided together")
    if heartbeat is not None and not isinstance(heartbeat, One1000Heartbeat):
        raise TypeError("ONE1000 heartbeat status is invalid")
    if sentryStatus is not None and not isinstance(
        sentryStatus,
        One1000SentryStatus,
    ):
        raise TypeError("ONE1000 sentry diagnostic status is invalid")

    connected = bool(
        serialOpen
        and heartbeat is not None
        and normalizedHeartbeatAge <= ONE1000_HEARTBEAT_TIMEOUT_SECONDS
    )
    return {
        "schema_version": "1.0",
        "timestamp": eventTimestamp,
        "source": "ONE1000",
        "serialPort": serialPort.strip(),
        "serialOpen": serialOpen,
        "connected": connected,
        "heartbeat": _BuildOne1000HeartbeatStatusValue(
            heartbeat,
            normalizedHeartbeatAge,
        ),
        "sentryStatus": _BuildOne1000SentryDiagnosticValue(
            sentryStatus,
            normalizedSentryAge,
        ),
    }


def _BuildOne1000HeartbeatStatusValue(
    heartbeat: One1000Heartbeat | None,
    ageSeconds: float | None,
) -> dict[str, Any] | None:
    """把最近一次 0x59 心跳转换成便于排障的状态字段。"""
    if heartbeat is None or ageSeconds is None:
        return None
    return {
        "counter": heartbeat.counter,
        "ageSeconds": ageSeconds,
        "rangingStatus": heartbeat.rangingStatus,
        "rangingState": _GetOne1000RangingStateValue(
            heartbeat.rangingStatus
        ),
        "radarStatus": heartbeat.radarStatus,
        "radarState": _GetOne1000RadarStateValue(heartbeat.radarStatus),
        "radarActive": heartbeat.radarStatus == 0x05,
    }


def _BuildOne1000SentryDiagnosticValue(
    sentryStatus: One1000SentryStatus | None,
    ageSeconds: float | None,
) -> dict[str, Any] | None:
    """把最近一次 0x54 哨兵结果转换成诊断字段。"""
    if sentryStatus is None or ageSeconds is None:
        return None
    return {
        "ageSeconds": ageSeconds,
        "rawStatus": sentryStatus.rawStatus,
        "detectionValid": sentryStatus.detectionValid,
        "livingBodyDetected": sentryStatus.livingBodyDetected,
        "headTouchDetected": sentryStatus.headTouchDetected,
        "maxRadarValue": sentryStatus.maxRadarValue,
        "livingBodyFirstIndex": sentryStatus.livingBodyFirstIndex,
    }


def _GetOne1000RangingStateValue(status: int) -> str:
    """把厂商测距状态码转换成可读名称。"""
    return {
        0x03: "DEINITIALIZED",
        0x05: "ACTIVE",
        0x06: "TIMEOUT",
    }.get(status, "UNKNOWN")


def _GetOne1000RadarStateValue(status: int) -> str:
    """把厂商雷达状态码转换成可读名称。"""
    return {
        0x03: "DEINITIALIZED",
        0x05: "ACTIVE",
        0x06: "RANGING_CONFLICT_TIMEOUT",
    }.get(status, "UNKNOWN")


def _NormalizeOptionalAgeSecondsValue(
    ageSeconds: float | None,
    fieldName: str,
) -> float | None:
    """校验并规整可空的真实时间状态年龄。"""
    if ageSeconds is None:
        return None
    if isinstance(ageSeconds, bool):
        raise TypeError(f"ONE1000 {fieldName} age must be numeric")
    normalizedAge = float(ageSeconds)
    if not isfinite(normalizedAge) or normalizedAge < 0:
        raise ValueError(f"ONE1000 {fieldName} age must be non-negative")
    return normalizedAge


class One1000TactileNode(Node):
    """读取 ONE1000 串口并发布摸头触觉事件。"""

    def __init__(self) -> None:
        """声明参数、打开串口并启动非阻塞读取定时器。"""
        if rclpy is None or String is None:
            raise RuntimeError(
                "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
            )
        super().__init__("one1000_tactile_node")
        self._DeclareParametersValue()
        serialPort = str(self.get_parameter("serial_port").value)
        self._autoStartSentry = bool(
            self.get_parameter("auto_start_sentry").value
        )
        self._touchThreshold = int(
            self.get_parameter("touch_threshold").value
        )
        self._commandIntervalSeconds = float(
            self.get_parameter("command_interval_seconds").value
        )
        cooldownSeconds = float(
            self.get_parameter("touch_cooldown_seconds").value
        )
        self._stopSentryOnShutdown = bool(
            self.get_parameter("stop_sentry_on_shutdown").value
        )
        self._ValidateNumericParametersValue(cooldownSeconds)

        self.eventPublisher = self.create_publisher(
            String,
            "/perception/tactile_event",
            _ReliableQoS(10),
        )
        self.statusPublisher = self.create_publisher(
            String,
            "/one1000/status",
            _ReliableQoS(10),
        )
        self._serialPort = serialPort
        self._serial = One1000SerialPort(serialPort)
        self._parser = One1000StreamParser()
        self._edgeDetector = One1000HeadPetEdgeDetector(cooldownSeconds)
        self._commandQueue: deque[tuple[int, bytes, str]] = deque()
        self._sequence = 0
        self._openedAt = time.monotonic()
        self._firstHeartbeatReceived = False
        self._startupCommandsQueued = False
        self._sentryStartSent = False
        self._nextCommandTimestamp = self._openedAt
        self._closed = False
        self._lastHeartbeatState: tuple[int, int] | None = None
        self._lastHeartbeat: One1000Heartbeat | None = None
        self._lastHeartbeatTimestamp: float | None = None
        self._lastSentryStatus: One1000SentryStatus | None = None
        self._lastSentryStatusTimestamp: float | None = None
        self._readTimer = self.create_timer(0.01, self.OnSerialTimer)
        self._statusTimer = self.create_timer(1.0, self.PublishStatusValue)
        self.get_logger().info(
            f"ONE1000 serial opened: {serialPort}, {ONE1000_SERIAL_BAUD_RATE} 8N1"
        )

    def _DeclareParametersValue(self) -> None:
        """声明仅允许启动时配置的 ONE1000 参数。"""
        self.declare_parameter(
            "serial_port",
            DEFAULT_ONE1000_SERIAL_PORT,
            descriptor=_ReadOnlyParameterDescriptor("ONE1000 serial device path"),
        )
        self.declare_parameter(
            "auto_start_sentry",
            True,
            descriptor=_ReadOnlyParameterDescriptor(
                "Configure threshold and start sentry automatically"
            ),
        )
        self.declare_parameter(
            "touch_threshold",
            30,
            descriptor=_ReadOnlyIntegerParameterDescriptor(
                "ONE1000 head-touch threshold", 1, 65535
            ),
        )
        self.declare_parameter(
            "command_interval_seconds",
            0.3,
            descriptor=_ReadOnlyParameterDescriptor(
                "Minimum interval between ONE1000 commands"
            ),
        )
        self.declare_parameter(
            "touch_cooldown_seconds",
            1.0,
            descriptor=_ReadOnlyParameterDescriptor(
                "Real-time cooldown between head-pet events"
            ),
        )
        self.declare_parameter(
            "stop_sentry_on_shutdown",
            True,
            descriptor=_ReadOnlyParameterDescriptor(
                "Stop sentry before closing the serial port"
            ),
        )

    def _ValidateNumericParametersValue(self, cooldownSeconds: float) -> None:
        """校验 ROS2 描述器无法约束的浮点参数。"""
        if (
            not isfinite(self._commandIntervalSeconds)
            or self._commandIntervalSeconds < 0.2
        ):
            raise ValueError("command_interval_seconds must be at least 0.2")
        if not isfinite(cooldownSeconds) or cooldownSeconds < 0:
            raise ValueError("touch_cooldown_seconds must be non-negative")
        BuildOne1000TouchThresholdValue(self._touchThreshold)

    def OnSerialTimer(self) -> None:
        """消费串口数据，并按协议间隔发送排队命令。"""
        if self._closed:
            return
        try:
            serialData = self._serial.ReadAvailableValue()
            for packet in self._parser.FeedBytesValue(serialData):
                for tlv in packet.tlvs:
                    self._HandleTLVValue(tlv)
            self._QueueStartupCommandsValue()
            self._SendNextCommandValue()
        except OSError as error:
            self.get_logger().error(f"ONE1000 serial I/O failed: {error}")
            self.ShutdownValue()

    def _HandleTLVValue(self, tlv: One1000TLV) -> None:
        """按 TLV 类型处理响应、心跳和摸头状态。"""
        response = ParseOne1000DeviceResponseValue(tlv)
        if response is not None:
            logMethod = (
                self.get_logger().info
                if response.status == 0
                else self.get_logger().warning
            )
            logMethod(
                "ONE1000 command response: type=0x%02X, status=%d"
                % (response.responseType, response.status)
            )
            return

        if tlv.typeValue == ONE1000_HEARTBEAT_TYPE:
            heartbeat = ParseOne1000HeartbeatValue(tlv)
            if heartbeat is not None:
                self._lastHeartbeat = heartbeat
                self._lastHeartbeatTimestamp = time.monotonic()
                self._firstHeartbeatReceived = True
                heartbeatState = (
                    heartbeat.rangingStatus,
                    heartbeat.radarStatus,
                )
                if heartbeatState != self._lastHeartbeatState:
                    self.get_logger().info(
                        "ONE1000 heartbeat: ranging=0x%02X, radar=0x%02X"
                        % heartbeatState
                    )
                    self._lastHeartbeatState = heartbeatState
            return

        if tlv.typeValue != ONE1000_SENTRY_STATUS_TYPE:
            return
        sentryStatus = ParseOne1000SentryStatusValue(tlv)
        if sentryStatus is None:
            return
        self._lastSentryStatus = sentryStatus
        self._lastSentryStatusTimestamp = time.monotonic()
        if self._edgeDetector.ShouldEmitEventValue(
            sentryStatus,
            time.monotonic(),
        ):
            self.PublishHeadPetEventValue(sentryStatus)

    def _QueueStartupCommandsValue(self) -> None:
        """首次心跳后依次排入阈值、清缓存和启动哨兵命令。"""
        if (
            not self._autoStartSentry
            or self._startupCommandsQueued
            or not self._firstHeartbeatReceived
            or time.monotonic() - self._openedAt < 0.5
        ):
            return
        self._commandQueue.extend(
            (
                (
                    ONE1000_TOUCH_THRESHOLD_TYPE,
                    BuildOne1000TouchThresholdValue(self._touchThreshold),
                    f"set touch threshold={self._touchThreshold}",
                ),
                (
                    ONE1000_SENTRY_CONTROL_TYPE,
                    bytes((ONE1000_SENTRY_CLEAR_CACHE_COMMAND,)),
                    "clear sentry cache",
                ),
                (
                    ONE1000_SENTRY_CONTROL_TYPE,
                    bytes((ONE1000_SENTRY_START_COMMAND,)),
                    "start sentry",
                ),
            )
        )
        self._startupCommandsQueued = True

    def _SendNextCommandValue(self) -> None:
        """到达最小命令间隔后发送队首命令。"""
        if not self._commandQueue or time.monotonic() < self._nextCommandTimestamp:
            return
        commandType, commandValue, description = self._commandQueue.popleft()
        self._WriteCommandValue(commandType, commandValue)
        if (
            commandType == ONE1000_SENTRY_CONTROL_TYPE
            and commandValue == bytes((ONE1000_SENTRY_START_COMMAND,))
        ):
            self._sentryStartSent = True
        self._nextCommandTimestamp = (
            time.monotonic() + self._commandIntervalSeconds
        )
        self.get_logger().info(f"ONE1000 command sent: {description}")

    def _WriteCommandValue(self, commandType: int, commandValue: bytes) -> None:
        """写入命令并递增 uint8 序号。"""
        packet = BuildOne1000CommandValue(
            self._sequence,
            commandType,
            commandValue,
        )
        self._serial.WriteValue(packet)
        self._sequence = (self._sequence + 1) & 0xFF

    def PublishHeadPetEventValue(
        self,
        sentryStatus: One1000SentryStatus,
    ) -> None:
        """发布单次摸头上升沿触觉事件。"""
        payload = BuildOne1000TactileEventValue(sentryStatus)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.eventPublisher.publish(message)
        self.get_logger().info(
            "Published EVT_TACTILE_HEAD_PET: rawStatus=0x%02X, radar=%.3f"
            % (sentryStatus.rawStatus, sentryStatus.maxRadarValue)
        )

    def PublishStatusValue(self) -> None:
        """以真实时间 1 Hz 发布串口、心跳和原始摸头诊断状态。"""
        monotonicTimestamp = time.monotonic()
        heartbeatAge = self._GetStatusAgeSecondsValue(
            monotonicTimestamp,
            self._lastHeartbeatTimestamp,
        )
        sentryStatusAge = self._GetStatusAgeSecondsValue(
            monotonicTimestamp,
            self._lastSentryStatusTimestamp,
        )
        payload = BuildOne1000StatusValue(
            serialPort=self._serialPort,
            serialOpen=not self._closed,
            heartbeat=self._lastHeartbeat,
            heartbeatAgeSeconds=heartbeatAge,
            sentryStatus=self._lastSentryStatus,
            sentryStatusAgeSeconds=sentryStatusAge,
        )
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.statusPublisher.publish(message)

    def _GetStatusAgeSecondsValue(
        self,
        currentTimestamp: float,
        statusTimestamp: float | None,
    ) -> float | None:
        """计算最近硬件状态距当前的真实秒数。"""
        if statusTimestamp is None:
            return None
        return max(0.0, currentTimestamp - statusTimestamp)

    def ShutdownValue(self) -> None:
        """必要时停止哨兵并恢复串口配置。"""
        if self._closed:
            return
        self._closed = True
        try:
            if self._stopSentryOnShutdown and self._sentryStartSent:
                # 关闭阶段只有一个短命令；确保与上一命令满足厂商要求的 200 ms 间隔。
                remainingSeconds = self._nextCommandTimestamp - time.monotonic()
                if remainingSeconds > 0:
                    time.sleep(remainingSeconds)
                self._WriteCommandValue(
                    ONE1000_SENTRY_CONTROL_TYPE,
                    bytes((ONE1000_SENTRY_STOP_COMMAND,)),
                )
                if rclpy.ok():
                    self.get_logger().info("ONE1000 sentry stopped")
        except OSError as error:
            if rclpy.ok():
                self.get_logger().warning(
                    f"Failed to stop ONE1000 sentry cleanly: {error}"
                )
        finally:
            self._serial.CloseValue()


def _ReliableQoS(depth: int):
    """创建 RELIABLE QoS，便于触觉离散事件可靠交付。"""
    if QoSProfile is None:
        return depth
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=depth,
        reliability=ReliabilityPolicy.RELIABLE,
    )


def _ReadOnlyParameterDescriptor(description: str):
    """创建启动后不可动态修改的 ROS2 参数描述。"""
    if ParameterDescriptor is None:
        return None
    return ParameterDescriptor(description=description, read_only=True)


def _ReadOnlyIntegerParameterDescriptor(
    description: str,
    minimumValue: int,
    maximumValue: int,
):
    """创建带闭区间约束的只读整数参数描述。"""
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


def main(args=None) -> None:
    """启动 ONE1000 触摸事件节点。"""
    if rclpy is None:
        raise RuntimeError(
            "ROS2 runtime is not available. Please run this node inside a ROS2 environment."
        )
    rclpy.init(args=args)
    node = None
    try:
        node = One1000TactileNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.ShutdownValue()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
