import struct
import unittest

from marsdog_core.one1000_protocol import (
    ONE1000_HEARTBEAT_TYPE,
    ONE1000_SENTRY_CONTROL_TYPE,
    ONE1000_SENTRY_STATUS_TYPE,
    BuildOne1000CommandValue,
    BuildOne1000PacketValue,
    BuildOne1000TouchThresholdValue,
    One1000HeadPetEdgeDetector,
    One1000Heartbeat,
    One1000SentryStatus,
    One1000StreamParser,
    One1000TLV,
    ParseOne1000HeartbeatValue,
    ParseOne1000SentryStatusValue,
)
from marsdog_ros2.one1000_tactile_node import (
    BuildOne1000StatusValue,
    BuildOne1000TactileEventValue,
)


class One1000ProtocolTest(unittest.TestCase):
    def test_vendor_sentry_commands_match_manual(self):
        """清缓存、启动和停止命令应与厂商手册示例逐字节一致。"""
        expectedPackets = {
            0x03: "55aa0003004a0103d93e",
            0x04: "55aa0003004a0104a9d9",
            0x05: "55aa0003004a0105b9f8",
        }

        for commandValue, expectedHex in expectedPackets.items():
            with self.subTest(commandValue=commandValue):
                packet = BuildOne1000CommandValue(
                    0,
                    ONE1000_SENTRY_CONTROL_TYPE,
                    bytes((commandValue,)),
                )
                self.assertEqual(packet.hex(), expectedHex)

    def test_stream_parser_handles_fragment_noise_and_multiple_tlvs(self):
        """流式解析器应跨分片跳过噪声并保留包内所有 TLV。"""
        packet = BuildOne1000PacketValue(
            7,
            (
                One1000TLV(ONE1000_HEARTBEAT_TYPE, bytes((4, 1, 5))),
                One1000TLV(0x00, bytes((0x4A, 0))),
            ),
        )
        parser = One1000StreamParser()

        self.assertEqual(parser.FeedBytesValue(b"noise\x55"), [])
        self.assertEqual(parser.FeedBytesValue(packet[:3]), [])
        parsedPackets = parser.FeedBytesValue(packet[3:])

        self.assertEqual(len(parsedPackets), 1)
        self.assertEqual(parsedPackets[0].sequence, 7)
        self.assertEqual([tlv.typeValue for tlv in parsedPackets[0].tlvs], [0x59, 0x00])

    def test_stream_parser_recovers_after_crc_failure(self):
        """CRC 错帧后紧随的有效帧仍应被解析。"""
        invalidPacket = bytearray(
            BuildOne1000PacketValue(1, (One1000TLV(0x59, b"\x01\x02\x03"),))
        )
        invalidPacket[-1] ^= 0xFF
        validPacket = BuildOne1000PacketValue(
            2,
            (One1000TLV(0x59, b"\x02\x03\x05"),),
        )

        packets = One1000StreamParser().FeedBytesValue(
            bytes(invalidPacket) + validPacket
        )

        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0].sequence, 2)

    def test_sentry_status_decodes_head_touch_bits(self):
        """0x54 的人体位、摸头位和调试字段应按小端结构解析。"""
        tlv = One1000TLV(
            ONE1000_SENTRY_STATUS_TYPE,
            struct.pack("<BfH", 0x03, 42.5, 17),
        )

        status = ParseOne1000SentryStatusValue(tlv)

        self.assertIsNotNone(status)
        self.assertTrue(status.detectionValid)
        self.assertTrue(status.livingBodyDetected)
        self.assertTrue(status.headTouchDetected)
        self.assertAlmostEqual(status.maxRadarValue, 42.5)
        self.assertEqual(status.livingBodyFirstIndex, 17)

    def test_invalid_sentry_status_is_not_a_touch(self):
        """厂商定义的 0xFF 无效状态不能触发摸头。"""
        status = ParseOne1000SentryStatusValue(
            One1000TLV(
                ONE1000_SENTRY_STATUS_TYPE,
                struct.pack("<BfH", 0xFF, 0.0, 0),
            )
        )

        self.assertFalse(status.detectionValid)
        self.assertFalse(status.livingBodyDetected)
        self.assertFalse(status.headTouchDetected)

    def test_heartbeat_and_touch_threshold_are_little_endian(self):
        """心跳状态和摸头阈值应符合厂商字段定义。"""
        heartbeat = ParseOne1000HeartbeatValue(
            One1000TLV(ONE1000_HEARTBEAT_TYPE, b"\x12\x01\x05")
        )

        self.assertEqual(heartbeat.counter, 0x12)
        self.assertEqual(heartbeat.rangingStatus, 0x01)
        self.assertEqual(heartbeat.radarStatus, 0x05)
        self.assertEqual(BuildOne1000TouchThresholdValue(30), b"\x1e\x00")

    def test_head_pet_detector_uses_rising_edge_and_real_cooldown(self):
        """连续高电平只触发一次，松手并超过冷却后才能再次触发。"""
        detector = One1000HeadPetEdgeDetector(cooldownSeconds=1.0)
        touched = self._BuildSentryStatusValue(True)
        released = self._BuildSentryStatusValue(False)

        self.assertTrue(detector.ShouldEmitEventValue(touched, 0.0))
        self.assertFalse(detector.ShouldEmitEventValue(touched, 0.1))
        self.assertFalse(detector.ShouldEmitEventValue(released, 0.2))
        self.assertFalse(detector.ShouldEmitEventValue(touched, 0.5))
        self.assertFalse(detector.ShouldEmitEventValue(released, 1.1))
        self.assertTrue(detector.ShouldEmitEventValue(touched, 1.2))

    def test_tactile_payload_uses_existing_head_pet_event(self):
        """ROS2 输出应复用已有 EVT_TACTILE_HEAD_PET 情绪事件名。"""
        payload = BuildOne1000TactileEventValue(
            self._BuildSentryStatusValue(True),
            timestamp=123.5,
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["timestamp"], 123.5)
        self.assertEqual(payload["event_type"], "EVT_TACTILE_HEAD_PET")
        self.assertEqual(payload["source"], "ONE1000")
        self.assertEqual(payload["sensorType"], "UWB_RADAR")
        self.assertEqual(payload["touchState"], "STARTED")

    def test_status_payload_reports_active_radar_and_raw_touch(self):
        """周期状态应同时暴露 0x59 雷达状态和 0x54 原始摸头位。"""
        payload = BuildOne1000StatusValue(
            serialPort="/dev/ttyUSB1",
            serialOpen=True,
            heartbeat=One1000Heartbeat(7, 0x06, 0x05),
            heartbeatAgeSeconds=0.2,
            sentryStatus=self._BuildSentryStatusValue(True),
            sentryStatusAgeSeconds=0.1,
            timestamp=123.5,
        )

        self.assertTrue(payload["connected"])
        self.assertEqual(payload["heartbeat"]["counter"], 7)
        self.assertEqual(payload["heartbeat"]["rangingState"], "TIMEOUT")
        self.assertEqual(payload["heartbeat"]["radarState"], "ACTIVE")
        self.assertTrue(payload["heartbeat"]["radarActive"])
        self.assertEqual(payload["sentryStatus"]["rawStatus"], 0x03)
        self.assertTrue(payload["sentryStatus"]["headTouchDetected"])

    def test_status_payload_reports_missing_or_stale_heartbeat(self):
        """无心跳或心跳超过2.5秒时 connected 应为 false。"""
        missingPayload = BuildOne1000StatusValue(
            "/dev/ttyUSB1",
            True,
            None,
            None,
            None,
            None,
            timestamp=1.0,
        )
        stalePayload = BuildOne1000StatusValue(
            "/dev/ttyUSB1",
            True,
            One1000Heartbeat(8, 0x06, 0x05),
            2.6,
            None,
            None,
            timestamp=2.0,
        )

        self.assertFalse(missingPayload["connected"])
        self.assertIsNone(missingPayload["heartbeat"])
        self.assertIsNone(missingPayload["sentryStatus"])
        self.assertFalse(stalePayload["connected"])
        self.assertEqual(stalePayload["heartbeat"]["radarState"], "ACTIVE")

    def test_status_payload_rejects_unpaired_status_age(self):
        """诊断对象与状态年龄必须成对提供。"""
        with self.assertRaises(ValueError):
            BuildOne1000StatusValue(
                "/dev/ttyUSB1",
                True,
                None,
                0.1,
                None,
                None,
                timestamp=1.0,
            )

    def test_invalid_threshold_values_are_rejected(self):
        """摸头阈值应拒绝布尔值、非整数和越界数值。"""
        for invalidValue in (True, 1.5, "30", 0, 65536):
            with self.subTest(invalidValue=invalidValue):
                with self.assertRaises((TypeError, ValueError)):
                    BuildOne1000TouchThresholdValue(invalidValue)

    def _BuildSentryStatusValue(self, touched: bool) -> One1000SentryStatus:
        """构造供边沿识别测试使用的有效哨兵状态。"""
        rawStatus = 0x03 if touched else 0x01
        return One1000SentryStatus(
            rawStatus=rawStatus,
            detectionValid=True,
            livingBodyDetected=True,
            headTouchDetected=touched,
            maxRadarValue=10.0,
            livingBodyFirstIndex=2,
        )


if __name__ == "__main__":
    unittest.main()
