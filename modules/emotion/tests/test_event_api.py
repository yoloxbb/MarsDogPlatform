import unittest

from marsdog_core import MarsdogBehaviorSystem


class EventAPITest(unittest.TestCase):
    def test_post_event_pushes_queue_and_calls_handler(self):
        """提交事件应进入队列并触发已注册处理器。"""
        system = MarsdogBehaviorSystem()
        received = []

        system.RegisterEventHandler("OwnerCall", lambda event: received.append(event.eventTag))
        self.assertTrue(system.PostEvent("OwnerCall", {"direction": "front"}))

        self.assertEqual(len(system.state.pendingEvents), 1)
        self.assertEqual(received, ["OwnerCall"])

    def test_unregister_event_handler(self):
        """取消注册后处理器不应继续收到事件。"""
        system = MarsdogBehaviorSystem()
        received = []

        def handler(event):
            received.append(event.eventTag)

        system.RegisterEventHandler("OwnerCall", handler)
        system.UnregisterEventHandler("OwnerCall", handler)
        system.PostEvent("OwnerCall", {})

        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
