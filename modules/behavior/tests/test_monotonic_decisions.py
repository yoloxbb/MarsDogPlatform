"""Elapsed-time decisions survive civil clock jumps; wire times stay civil."""
import unittest
from types import SimpleNamespace

from bionic_dog_bt.blackboard import Blackboard
from marsdog_behavior.candidate_pool import CandidatePool


class Clock:
    def __init__(self):
        self.wall = 1000.0
        self.elapsed = 10.0

    def monotonic(self):
        return self.elapsed

    def wall_time(self):
        return self.wall


class MonotonicDecisionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.bb = Blackboard(monotonic=self.clock.monotonic, wall_time=self.clock.wall_time)
        self.pool = CandidatePool(monotonic=self.clock.monotonic, wall_time=self.clock.wall_time)

    def test_running_timeout_follows_elapsed_time_in_both_wall_directions(self):
        active = SimpleNamespace(behavior_name="walk", timeout_sec=30)
        self.bb.start_behavior(active, "goal")
        for wall in (900000, -900000):
            self.clock.wall = wall
            self.assertFalse(self.bb.check_timeout())
        self.clock.elapsed = 40
        self.assertTrue(self.bb.check_timeout())
        self.assertEqual(self.bb.current_goal_id, "goal")
        active.timeout_sec = 0
        self.assertFalse(self.bb.check_timeout())

    def test_cooldown_keeps_wall_diagnostic_but_expires_on_elapsed_deadline(self):
        self.bb.set_cooldown("walk", 5)
        self.assertEqual(self.bb.cooldown_until["walk"], 1005)
        for wall in (900000, -900000):
            self.clock.wall = wall
            self.assertTrue(self.bb.is_in_cooldown("walk"))
        self.clock.elapsed = 15
        self.assertFalse(self.bb.is_in_cooldown("walk"))

    def test_legacy_seeded_cooldown_is_anchored_once_and_can_be_replaced(self):
        self.bb.cooldown_until["walk"] = 1005
        self.assertTrue(self.bb.is_in_cooldown("walk"))
        self.clock.wall = -1000
        self.clock.elapsed = 15
        self.assertFalse(self.bb.is_in_cooldown("walk"))
        self.bb.cooldown_until["walk"] = -990
        self.assertTrue(self.bb.is_in_cooldown("walk"))

    def test_positive_ttl_survives_wall_jumps_then_releases_dedup(self):
        self.assertTrue(self.pool.add("walk", 3, ttl_sec=5))
        original = self.pool.candidates[0]
        self.assertEqual(original["created_at"], 1000)
        for wall in (900000, -900000):
            self.clock.wall = wall
            self.assertEqual(self.pool.size(), 1)
            self.assertTrue(self.pool.is_duplicate("walk"))
        self.clock.elapsed = 15
        self.assertIsNone(self.pool.select_best(self.bb))
        self.assertFalse(self.pool.is_duplicate("walk"))
        self.assertTrue(self.pool.add("walk", 3, ttl_sec=5))

    def test_initial_event_age_is_preserved_and_nonpositive_ttl_is_unbounded(self):
        self.pool.add("old", 3, created_at=990, ttl_sec=5)
        self.pool.add("unbounded", 3, created_at=1, ttl_sec=0)
        self.pool.add("negative", 3, created_at=1, ttl_sec=-1)
        self.clock.elapsed = 90000
        self.assertEqual({c["behavior_name"] for c in self.pool.candidates}, {"unbounded", "negative"})

    def test_duplicate_caller_ids_have_independent_deadlines(self):
        self.pool.add("short", 3, candidate_id="shared", ttl_sec=1)
        self.pool.add("long", 3, candidate_id="shared", ttl_sec=5)
        self.clock.elapsed = 11
        candidate = self.pool.select_best(self.bb)
        self.assertEqual(candidate["behavior_name"], "long")
        self.assertFalse(any("monotonic" in key for key in candidate))

    def test_removals_do_not_leave_expiry_records_or_release_running_goal(self):
        for remove in (
            lambda: self.pool.discard_where(lambda _: True),
            lambda: self.pool.clear(),
            lambda: self.pool.select_best(self.bb),
        ):
            self.pool.add("walk", 3, ttl_sec=1)
            remove()
            self.assertEqual(self.pool._expires_at, {})
            self.pool.clear()
        self.pool.add("walk", 3, ttl_sec=1)
        claimed = self.pool.select_best(self.bb)
        self.clock.elapsed = 1000
        self.assertEqual(self.pool.size(), 0)
        self.assertFalse(self.pool.add("walk", 3))
        self.assertTrue(self.pool.release_inflight("walk", claimed["candidate_id"]))


if __name__ == "__main__":
    unittest.main()
