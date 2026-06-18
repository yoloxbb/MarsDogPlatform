import unittest

from marsdog_core import MarsdogBehaviorSystem


class DebugAPITest(unittest.TestCase):
    def test_get_system_status_includes_sleep_state(self):
        """系统状态摘要应包含睡眠状态机字段。"""
        system = MarsdogBehaviorSystem()
        system.SetDemandValue("Sleepiness", 80)
        system.Tick(currentTime=9)

        status = system.GetSystemStatus()

        self.assertEqual(status.currentAction, "ACTION_SLEEP")
        self.assertTrue(status.sleepActionAllowed)
        self.assertEqual(status.shallowSleepTicksRemaining, 0)


if __name__ == "__main__":
    unittest.main()
