import unittest

from marsdog_ros2.common.calculation_time import (
    DeclareCalculationTimeParametersValue,
)
from marsdog_ros2.common.json_message import NormalizeJsonMessageValue
from marsdog_ros2.common.qos import (
    BestEffortQoSValue,
    ReliableQoSValue,
    ReliableTransientLocalQoSValue,
)


class _StringMessage:
    """模拟 std_msgs/String 的最小消息对象。"""

    def __init__(self, data: str) -> None:
        """保存测试需要的 data 字段。"""
        self.data = data


class _ParameterNode:
    """记录公共时间参数声明结果的最小节点。"""

    def __init__(self) -> None:
        """初始化参数记录列表。"""
        self.parameters: list[tuple[str, object, object]] = []

    def declare_parameter(
        self,
        name: str,
        defaultValue: object,
        descriptor: object,
    ) -> None:
        """记录一次参数声明，供测试核对名称和默认值。"""
        self.parameters.append((name, defaultValue, descriptor))


class Ros2CommonTest(unittest.TestCase):
    def test_json_message_normalizes_supported_inputs(self):
        """公共 JSON 工具应兼容字典、字符串和 ROS2 String。"""
        original = {"event_type": "EVT_TEST"}
        normalized = NormalizeJsonMessageValue(original)

        self.assertEqual(normalized, original)
        self.assertIsNot(normalized, original)
        self.assertEqual(
            NormalizeJsonMessageValue('{"event_type":"EVT_TEST"}'),
            original,
        )
        self.assertEqual(
            NormalizeJsonMessageValue(
                _StringMessage('{"event_type":"EVT_TEST"}')
            ),
            original,
        )

    def test_json_message_rejects_invalid_or_non_object_values(self):
        """公共 JSON 工具应忽略非法 JSON 和非对象结果。"""
        self.assertEqual(NormalizeJsonMessageValue("invalid"), {})
        self.assertEqual(NormalizeJsonMessageValue("[]"), {})
        self.assertEqual(NormalizeJsonMessageValue(None), {})

    def test_qos_helpers_keep_requested_depth(self):
        """公共 QoS 工具在有无 ROS2 环境时都应保留队列深度。"""
        for qosValue in (
            BestEffortQoSValue(5),
            ReliableQoSValue(10),
            ReliableTransientLocalQoSValue(1000),
        ):
            if isinstance(qosValue, int):
                self.assertIn(qosValue, {5, 10, 1000})
            else:
                self.assertIn(qosValue.depth, {5, 10, 1000})

    def test_calculation_time_parameters_are_declared_once(self):
        """需求和情绪节点应共用相同的启动时间参数集合。"""
        node = _ParameterNode()

        DeclareCalculationTimeParametersValue(node)

        self.assertEqual(
            [(name, value) for name, value, _ in node.parameters],
            [
                ("time_scale", 1),
                ("virtual_start_time", "auto"),
                ("random_seed", -1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
