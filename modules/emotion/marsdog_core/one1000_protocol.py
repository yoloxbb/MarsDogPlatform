"""全迹 ONE1000 UART 协议和摸头边沿识别。"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from struct import pack, unpack
from typing import Iterable


ONE1000_PACKET_HEADER = b"\x55\xAA"
ONE1000_DEVICE_RESPONSE_TYPE = 0x00
ONE1000_SENTRY_CONTROL_TYPE = 0x4A
ONE1000_SENTRY_STATUS_TYPE = 0x54
ONE1000_TOUCH_THRESHOLD_TYPE = 0x57
ONE1000_HEARTBEAT_TYPE = 0x59
ONE1000_SENTRY_CLEAR_CACHE_COMMAND = 0x03
ONE1000_SENTRY_START_COMMAND = 0x04
ONE1000_SENTRY_STOP_COMMAND = 0x05


@dataclass(frozen=True)
class One1000TLV:
    """表示 ONE1000 数据包中的单个 TLV。"""

    typeValue: int
    value: bytes


@dataclass(frozen=True)
class One1000Packet:
    """表示一个通过 CRC 校验的 ONE1000 UART 数据包。"""

    sequence: int
    tlvs: tuple[One1000TLV, ...]


@dataclass(frozen=True)
class One1000DeviceResponse:
    """表示设备对主机命令的统一响应。"""

    responseType: int
    status: int


@dataclass(frozen=True)
class One1000Heartbeat:
    """表示 ONE1000 每秒上报的工作状态。"""

    counter: int
    rangingStatus: int
    radarStatus: int


@dataclass(frozen=True)
class One1000SentryStatus:
    """表示 ONE1000 哨兵和摸头检测结果。"""

    rawStatus: int
    detectionValid: bool
    livingBodyDetected: bool
    headTouchDetected: bool
    maxRadarValue: float
    livingBodyFirstIndex: int


def CalculateOne1000CRCValue(data: bytes | bytearray | memoryview) -> int:
    """按照厂商协议计算 CRC16-XMODEM。"""
    crcValue = 0
    for byteValue in bytes(data):
        crcValue ^= byteValue << 8
        for _ in range(8):
            # XMODEM 多项式为 0x1021，所有计算都限制在16位内。
            crcValue = (
                ((crcValue << 1) ^ 0x1021) & 0xFFFF
                if crcValue & 0x8000
                else (crcValue << 1) & 0xFFFF
            )
    return crcValue


def BuildOne1000PacketValue(
    sequence: int,
    tlvs: Iterable[One1000TLV],
) -> bytes:
    """构造带帧头、长度和 CRC 的 ONE1000 数据包。"""
    normalizedSequence = _NormalizeByteValue(sequence, "sequence")
    tlvData = bytearray()
    for tlv in tlvs:
        if not isinstance(tlv, One1000TLV):
            raise TypeError("ONE1000 tlv must be One1000TLV")
        typeValue = _NormalizeByteValue(tlv.typeValue, "tlv type")
        value = bytes(tlv.value)
        if len(value) > 0xFF:
            raise ValueError("ONE1000 tlv value must not exceed 255 bytes")
        tlvData.extend((typeValue, len(value)))
        tlvData.extend(value)

    if not tlvData or len(tlvData) > 0xFFFF:
        raise ValueError("ONE1000 packet must contain valid TLV data")
    crcValue = CalculateOne1000CRCValue(tlvData)
    return b"".join(
        (
            ONE1000_PACKET_HEADER,
            bytes((normalizedSequence,)),
            len(tlvData).to_bytes(2, "little"),
            bytes(tlvData),
            crcValue.to_bytes(2, "big"),
        )
    )


def BuildOne1000CommandValue(
    sequence: int,
    commandType: int,
    value: bytes | bytearray | memoryview,
) -> bytes:
    """构造只包含一个命令 TLV 的 ONE1000 数据包。"""
    return BuildOne1000PacketValue(
        sequence,
        (One1000TLV(commandType, bytes(value)),),
    )


def ParseOne1000DeviceResponseValue(
    tlv: One1000TLV,
) -> One1000DeviceResponse | None:
    """解析 `0x00 DEVICE_RSP`，格式不匹配时返回 None。"""
    if tlv.typeValue != ONE1000_DEVICE_RESPONSE_TYPE or len(tlv.value) != 2:
        return None
    return One1000DeviceResponse(tlv.value[0], tlv.value[1])


def ParseOne1000HeartbeatValue(tlv: One1000TLV) -> One1000Heartbeat | None:
    """解析 `0x59 NOTIRY_HEART`，格式不匹配时返回 None。"""
    if tlv.typeValue != ONE1000_HEARTBEAT_TYPE or len(tlv.value) != 3:
        return None
    return One1000Heartbeat(tlv.value[0], tlv.value[1], tlv.value[2])


def ParseOne1000SentryStatusValue(
    tlv: One1000TLV,
) -> One1000SentryStatus | None:
    """解析 `0x54` 哨兵和摸头状态。"""
    if tlv.typeValue != ONE1000_SENTRY_STATUS_TYPE or len(tlv.value) != 7:
        return None
    rawStatus, maxRadarValue, firstIndex = unpack("<BfH", tlv.value)
    detectionValid = rawStatus != 0xFF
    return One1000SentryStatus(
        rawStatus=rawStatus,
        detectionValid=detectionValid,
        livingBodyDetected=detectionValid and bool(rawStatus & 0x01),
        headTouchDetected=detectionValid and bool(rawStatus & 0x02),
        maxRadarValue=float(maxRadarValue),
        livingBodyFirstIndex=int(firstIndex),
    )


def BuildOne1000TouchThresholdValue(touchThreshold: int) -> bytes:
    """把摸头灵敏度阈值编码为 `0x57` 的小端 uint16 Value。"""
    if isinstance(touchThreshold, bool) or not isinstance(touchThreshold, int):
        raise TypeError("ONE1000 touch threshold must be an integer")
    if touchThreshold < 1 or touchThreshold > 0xFFFF:
        raise ValueError("ONE1000 touch threshold must be between 1 and 65535")
    return pack("<H", touchThreshold)


class One1000StreamParser:
    """从任意分片的 UART 字节流中恢复通过校验的数据包。"""

    def __init__(self, maxTlvLength: int = 1024) -> None:
        """初始化带最大 TLV 长度保护的流式解析器。"""
        if isinstance(maxTlvLength, bool) or not isinstance(maxTlvLength, int):
            raise TypeError("ONE1000 max TLV length must be an integer")
        if maxTlvLength < 2 or maxTlvLength > 0xFFFF:
            raise ValueError("ONE1000 max TLV length is invalid")
        self.maxTlvLength = maxTlvLength
        self._buffer = bytearray()

    def FeedBytesValue(
        self,
        data: bytes | bytearray | memoryview,
    ) -> list[One1000Packet]:
        """追加一段串口数据并返回其中所有完整有效包。"""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("ONE1000 stream data must be bytes-like")
        self._buffer.extend(bytes(data))
        packets: list[One1000Packet] = []

        while True:
            if not self._AlignPacketHeaderValue():
                break
            if len(self._buffer) < 5:
                break

            tlvTotalLength = int.from_bytes(self._buffer[3:5], "little")
            if tlvTotalLength < 2 or tlvTotalLength > self.maxTlvLength:
                # 长度异常时只丢弃首字节，保留后续可能存在的新帧头。
                del self._buffer[0]
                continue

            packetLength = 5 + tlvTotalLength + 2
            if len(self._buffer) < packetLength:
                break

            packetBytes = bytes(self._buffer[:packetLength])
            tlvData = packetBytes[5:5 + tlvTotalLength]
            receivedCRC = int.from_bytes(packetBytes[-2:], "big")
            if CalculateOne1000CRCValue(tlvData) != receivedCRC:
                # CRC 失败也按单字节滑动重新同步，避免吞掉紧随其后的有效帧。
                del self._buffer[0]
                continue

            del self._buffer[:packetLength]
            parsedTlvs = self._ParseTLVsValue(tlvData)
            if parsedTlvs is not None:
                packets.append(One1000Packet(packetBytes[2], parsedTlvs))

        return packets

    def ResetValue(self) -> None:
        """清空尚未组成完整包的串口缓存。"""
        self._buffer.clear()

    def _AlignPacketHeaderValue(self) -> bool:
        """丢弃帧头前噪声，并保留可能的半个帧头。"""
        headerIndex = self._buffer.find(ONE1000_PACKET_HEADER)
        if headerIndex >= 0:
            if headerIndex:
                del self._buffer[:headerIndex]
            return True
        if self._buffer[-1:] == ONE1000_PACKET_HEADER[:1]:
            del self._buffer[:-1]
        else:
            self._buffer.clear()
        return False

    def _ParseTLVsValue(
        self,
        tlvData: bytes,
    ) -> tuple[One1000TLV, ...] | None:
        """解析一个包内可能连续存在的多个 TLV。"""
        result: list[One1000TLV] = []
        cursor = 0
        while cursor < len(tlvData):
            if cursor + 2 > len(tlvData):
                return None
            typeValue = tlvData[cursor]
            valueLength = tlvData[cursor + 1]
            valueEnd = cursor + 2 + valueLength
            if valueEnd > len(tlvData):
                return None
            result.append(One1000TLV(typeValue, tlvData[cursor + 2:valueEnd]))
            cursor = valueEnd
        return tuple(result) if result else None


class One1000HeadPetEdgeDetector:
    """把连续摸头状态转换成带防抖冷却的单次事件。"""

    def __init__(self, cooldownSeconds: float = 1.0) -> None:
        """初始化真实时间冷却窗口。"""
        if isinstance(cooldownSeconds, bool):
            raise TypeError("ONE1000 touch cooldown must be numeric")
        normalizedCooldown = float(cooldownSeconds)
        if not isfinite(normalizedCooldown) or normalizedCooldown < 0:
            raise ValueError("ONE1000 touch cooldown must be finite and non-negative")
        self.cooldownSeconds = normalizedCooldown
        self._touchActive = False
        self._lastEventTimestamp: float | None = None

    def ShouldEmitEventValue(
        self,
        sentryStatus: One1000SentryStatus,
        monotonicTimestamp: float,
    ) -> bool:
        """仅在有效摸头状态的上升沿且冷却结束后返回 True。"""
        if not isinstance(sentryStatus, One1000SentryStatus):
            raise TypeError("ONE1000 sentry status is invalid")
        if isinstance(monotonicTimestamp, bool):
            raise TypeError("ONE1000 touch timestamp must be numeric")
        timestamp = float(monotonicTimestamp)
        if not isfinite(timestamp):
            raise ValueError("ONE1000 touch timestamp must be finite")

        if not sentryStatus.detectionValid:
            # 无效探测不能被当成松手，保留上一次可靠状态。
            return False
        if not sentryStatus.headTouchDetected:
            self._touchActive = False
            return False
        if self._touchActive:
            return False

        self._touchActive = True
        if (
            self._lastEventTimestamp is not None
            and timestamp - self._lastEventTimestamp < self.cooldownSeconds
        ):
            return False
        self._lastEventTimestamp = timestamp
        return True


def _NormalizeByteValue(value: object, fieldName: str) -> int:
    """校验协议中的 uint8 字段。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"ONE1000 {fieldName} must be an integer")
    if value < 0 or value > 0xFF:
        raise ValueError(f"ONE1000 {fieldName} must be between 0 and 255")
    return value
