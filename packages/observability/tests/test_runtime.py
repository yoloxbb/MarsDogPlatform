import asyncio
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from marsdog_observability import bind_context, configure, emit, get_stats, shutdown, wrap_context
from marsdog_observability.runtime import Session
from marsdog_observability.formatting import BoundedFileHandler, StructuredLogger


class LogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.env = patch.dict("os.environ", {"MARSDOG_LOG_DIR": str(self.path), "MARSDOG_RUN_ID": "test-run",
                                            "MARSDOG_LOG_LEVEL": "DEBUG", "MARSDOG_LOG_DISABLED": "0"})
        self.env.start()
        self.original_level = logging.getLogger().level
        shutdown()

    def tearDown(self):
        shutdown()
        logging.getLogger().setLevel(self.original_level)
        self.env.stop()
        self.temp.cleanup()

    def rows(self):
        return [json.loads(line) for p in self.path.glob("*.jsonl*") for line in p.read_text().splitlines()]

    def test_python_logging_once_and_exceptions_preserved(self):
        first = configure("voice")
        self.assertIs(configure("voice"), first)
        try:
            raise ValueError("test failure")
        except ValueError:
            logging.getLogger("provider").error("failed %s", "model", exc_info=True)
        self.assertTrue(shutdown())
        rows = [r for r in self.rows() if r["event_name"] == "log.message"]
        self.assertEqual(len(rows), 1)
        self.assertIn("ValueError: test failure", rows[0]["exception"])
        self.assertEqual(rows[0]["run_id"], "test-run")
        self.assertEqual(rows[0]["message"], "failed model")
        health = json.loads(next(self.path.glob("*.health.json")).read_text())
        self.assertTrue(health["closed"])
        self.assertFalse(health["writer_alive"])
        self.assertEqual(health["pending"], 0)

    def test_thread_context_capture_isolated_and_reset(self):
        configure("behavior")
        with bind_context(interaction_id="one", goal_id="old"):
            callback = wrap_context(lambda: emit("callback"))
        with bind_context(interaction_id="two", goal_id="new"):
            t = threading.Thread(target=callback)
            t.start()
            emit("main")
            t.join()
        emit("outside")
        shutdown()
        rows = {r["event_name"]: r for r in self.rows()}
        self.assertEqual(rows["callback"]["interaction_id"], "one")
        self.assertEqual(rows["main"]["goal_id"], "new")
        self.assertNotIn("goal_id", rows["outside"])

    def test_async_contexts_do_not_leak(self):
        configure("voice")
        async def work(uid):
            with bind_context(utterance_id=uid):
                await asyncio.sleep(0)
                emit("async")
        async def run():
            await asyncio.gather(work("one"), work("two"))
        asyncio.run(run())
        shutdown()
        self.assertEqual({r["utterance_id"] for r in self.rows() if r["event_name"] == "async"}, {"one", "two"})

    def test_restart_changes_instance_but_preserves_run(self):
        one = configure("action").instance_id
        shutdown()
        two = configure("action").instance_id
        shutdown()
        self.assertNotEqual(one, two)
        self.assertEqual({r["run_id"] for r in self.rows()}, {"test-run"})

    def test_bounded_queue_never_waits_for_blocked_sink_and_reserves_priority(self):
        entered, release = threading.Event(), threading.Event()
        class Sink:
            def emit(self, record):
                entered.set()
                release.wait(3)
            def close(self):
                pass
        session = Session("action", self.path, "queue", capacity=2, priority_capacity=2, sink=Sink())
        try:
            session.record("first")
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            for i in range(100):
                session.record("telemetry", {"index": i})
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(session.record("action.terminal", {"goal_id": "one"}))
            self.assertGreater(session.snapshot()["dropped"], 0)
            self.assertLessEqual(session.snapshot()["pending"], 4)
        finally:
            release.set()
            self.assertTrue(session.close())

    def test_broken_sink_is_counted_and_does_not_throw_into_caller(self):
        blocked = self.path / "not-directory"
        blocked.write_text("keep")
        session = Session("action", blocked, "failure")
        self.assertTrue(session.record("action.result"))
        self.assertTrue(session.close())
        self.assertGreater(session.snapshot()["sink_errors"], 0)
        self.assertEqual(blocked.read_text(), "keep")

    def test_utf8_rotation_and_oversized_json_stay_bounded(self):
        session = Session("vision", self.path, "rotation", max_bytes=4096, backups=2)
        for i in range(100):
            session.record("sample", {"text": "测" * 300, "index": i})
        session.record("oversized", {"items": ["大" * 4000] * 30})
        session.record("🔥" * 128, {k: "🔥" * 4000 for k in
                       ("interaction_id", "utterance_id", "wake_id", "candidate_id",
                        "goal_id", "behavior_id", "target_id", "vision_epoch")}, logger="🔥" * 256)
        self.assertTrue(session.close())
        paths = list(self.path.glob("*.jsonl*"))
        self.assertLessEqual(len(paths), 3)
        self.assertTrue(all(p.stat().st_size <= 4096 for p in paths))
        self.assertTrue(self.rows())
        self.assertTrue(all(r.get("log_schema_version") == 1 for r in self.rows()))
        self.assertGreater(session.snapshot()["oversized"], 0)

    def test_repeat_reason_changes_and_secret_fields(self):
        configure("behavior")
        emit("waiting", {"reason": "cooldown", "api_key": "secret"}, repeat_key="candidate")
        emit("waiting", {"reason": "cooldown", "api_key": "secret"}, repeat_key="candidate")
        emit("waiting", {"reason": "cancel"}, repeat_key="candidate")
        self.assertEqual(get_stats()["coalesced"], 1)
        shutdown()
        rows = [r for r in self.rows() if r["event_name"] == "waiting"]
        self.assertEqual(len(rows), 2)
        self.assertNotIn("secret", json.dumps(rows))

    def test_standard_logging_kwargs_and_legacy_text_survive(self):
        logger = StructuredLogger("compat")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        logger.info("item %s", "one", stage="asr", extra={"other": True})
        self.assertEqual(records[0].getMessage(), "item one  stage='asr'")
        self.assertTrue(records[0].other)
        self.assertEqual(records[0].marsdog_fields["stage"], "asr")

    def test_disabled_mode_has_no_files(self):
        with patch.dict("os.environ", {"MARSDOG_LOG_DISABLED": "1"}):
            self.assertIsNone(configure("voice"))
            self.assertFalse(emit("ignored"))
        self.assertEqual(list(self.path.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
