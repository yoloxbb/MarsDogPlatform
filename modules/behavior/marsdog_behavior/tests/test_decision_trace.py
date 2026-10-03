"""Tracing may observe decisions; unavailable output must not change them."""
import json
from pathlib import Path
from types import SimpleNamespace
from marsdog_behavior import decision_trace
from marsdog_behavior.candidate_pool import CandidatePool


def records(directory):
    return [json.loads(line) for path in directory.glob("*.jsonl") for line in path.read_text().splitlines()]


def test_disabled_trace_has_no_filesystem_side_effect(monkeypatch):
    monkeypatch.delenv("MARSDOG_DECISION_TRACE_DIR", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Trace must not touch filesystem while disabled")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    decision_trace.emit("ignored", params="malformed")


def test_identity_allowlist_and_repeated_wait_coalescing(monkeypatch, tmp_path):
    monkeypatch.setenv("MARSDOG_DECISION_TRACE_DIR", str(tmp_path))
    item = {"candidate_id": "candidate", "params": {"interaction_id": "session", "utterance_id": "turn", "secret": "not logged"}}
    decision_trace.emit("candidate_waiting", item, repeat_key="candidate", reason="cooldown")
    decision_trace.emit("candidate_waiting", item, repeat_key="candidate", reason="cooldown")
    decision_trace.emit("candidate_waiting", item, repeat_key="candidate", reason="interaction_gate")
    rows = records(tmp_path)
    assert len(rows) == 2
    assert rows[0]["interaction_id"] == "session" and rows[0]["utterance_id"] == "turn"
    assert rows[0]["schema_version"] == 1
    assert "secret" not in json.dumps(rows)
    assert rows[0]["monotonic_ns"] <= rows[1]["monotonic_ns"]


def test_unwritable_sink_and_malformed_values_are_fail_open(monkeypatch, tmp_path):
    sink = tmp_path / "file"
    sink.write_text("preserve")
    monkeypatch.setenv("MARSDOG_DECISION_TRACE_DIR", str(sink))
    decision_trace.emit("blocked_filesystem", {"params": {}})
    decision_trace.emit("bad_params", {"params": "bad"})
    decision_trace.emit("bad_serialization", value=float("nan"))
    assert sink.read_text() == "preserve"


def test_trace_does_not_change_queue_priority_dedup_or_ownership(monkeypatch, tmp_path):
    def exercise():
        pool = CandidatePool()
        board = SimpleNamespace(is_in_cooldown=lambda name: name == "cooling")
        assert pool.add("emotion", 5, candidate_id="emotion", created_at=1, ttl_sec=0)
        assert pool.add("need", 2, candidate_id="need", created_at=1, ttl_sec=0)
        assert pool.add("cooling", 1, candidate_id="cooling", created_at=1, ttl_sec=0)
        assert not pool.add("need", 1)
        selected = pool.select_best(board)
        assert selected["candidate_id"] == "need"
        assert not pool.add("need", 1, allow_repeat=True)
        pool.release_inflight("need", "need")
        assert pool.add("need", 2, candidate_id="need-2", created_at=1, ttl_sec=0)
        return selected, pool.select_best(board)
    monkeypatch.delenv("MARSDOG_DECISION_TRACE_DIR", raising=False)
    plain = exercise()
    monkeypatch.setenv("MARSDOG_DECISION_TRACE_DIR", str(tmp_path / "valid"))
    assert exercise() == plain
    sink = tmp_path / "invalid"
    sink.write_text("not a directory")
    monkeypatch.setenv("MARSDOG_DECISION_TRACE_DIR", str(sink))
    assert exercise() == plain


def test_concurrent_writes_are_complete_json_records(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("MARSDOG_DECISION_TRACE_DIR", str(tmp_path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: decision_trace.emit("test", goal_id=str(index)), range(40)))
    assert {r["goal_id"] for r in records(tmp_path)} == {str(i) for i in range(40)}
