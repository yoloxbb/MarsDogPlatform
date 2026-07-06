import unittest

from marsdog_core import MarsdogNeedSystem


class EventAPITest(unittest.TestCase):
    def test_post_event_queues_event_and_calls_handler(self):
        """PostEvent 应入队并通知注册处理器。"""
        system = MarsdogNeedSystem()
        received = []

        system.RegisterEventHandler("OwnerCall", lambda event: received.append(event))
        accepted = system.PostEvent("OwnerCall", {"value": 90})

        self.assertTrue(accepted)
        self.assertEqual(len(system.state.pendingEvents), 1)
        self.assertEqual(received[0].eventTag, "OwnerCall")
        self.assertEqual(received[0].metadata["value"], 90)

    def test_unregister_event_handler(self):
        """取消注册后处理器不应再被调用。"""
        system = MarsdogNeedSystem()
        received = []

        def Handler(event):
            received.append(event)

        system.RegisterEventHandler("OwnerCall", Handler)
        system.UnregisterEventHandler("OwnerCall", Handler)
        system.PostEvent("OwnerCall", {})

        self.assertEqual(received, [])

    def test_empty_event_is_rejected(self):
        """空事件名不应进入事件队列。"""
        system = MarsdogNeedSystem()

        self.assertFalse(system.PostEvent("", {}))
        self.assertEqual(system.state.pendingEvents, [])


if __name__ == "__main__":
    unittest.main()
