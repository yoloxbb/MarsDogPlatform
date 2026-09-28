import json
import io
import logging

from marsdog_vision_interaction.utils import logging_utils


def test_vision_trace_is_correlated_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(logging_utils, "time_monotonic_ms", lambda: 1234.5)
    logging_utils.configure_event_trace(
        enabled=True,
        log_dir=str(tmp_path),
        run_id="run-01",
        case_id="STOP-01-r1",
    )

    logging_utils.vision_trace(
        "event_publish",
        result="published",
        event_type="EVT_VISION_STOP_GESTURE",
        latency_ms=12.3,
    )
    logging.shutdown()

    trace_file = next(tmp_path.glob("vision_trace_*.jsonl"))
    line = trace_file.read_text(encoding="utf-8").strip()
    assert line.startswith("VISION_TRACE ")
    payload = json.loads(line.removeprefix("VISION_TRACE "))
    assert payload["schema_version"] == 1
    assert payload["record"] == "event_publish"
    assert payload["run_id"] == "run-01"
    assert payload["case_id"] == "STOP-01-r1"
    assert payload["monotonic_ms"] == 1234.5
    assert payload["event_type"] == "EVT_VISION_STOP_GESTURE"


def test_disabled_vision_trace_creates_no_file(tmp_path) -> None:
    logging_utils.configure_event_trace(enabled=False, log_dir=str(tmp_path))
    logging_utils.vision_trace("runtime_start", result="ready")
    assert list(tmp_path.iterdir()) == []


def test_continuous_timing_trace_is_rate_limited_but_failures_are_not(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(logging_utils, "time_monotonic_ms", lambda: 1000.0)
    logging_utils.configure_event_trace(
        enabled=True,
        log_dir=str(tmp_path),
        timing_interval_sec=5.0,
    )

    assert logging_utils.vision_timing_trace(
        node="vision_observation",
        module="pose_landmarker",
        stage="inference",
        latency_ms=12.3456,
    )
    assert not logging_utils.vision_timing_trace(
        node="vision_observation",
        module="pose_landmarker",
        stage="inference",
        latency_ms=13.0,
    )
    assert logging_utils.vision_timing_trace(
        node="vision_observation",
        module="pose_landmarker",
        stage="inference",
        latency_ms=1.0,
        result="failure",
    )
    logging.shutdown()

    trace_file = next(tmp_path.glob("vision_trace_*.jsonl"))
    payloads = [
        json.loads(line.removeprefix("VISION_TRACE "))
        for line in trace_file.read_text(encoding="utf-8").splitlines()
    ]
    assert len(payloads) == 2
    assert payloads[0]["record"] == "stage_complete"
    assert payloads[0]["latency_ms"] == 12.346
    assert payloads[0]["sampled"] is True
    assert payloads[1]["result"] == "failure"
    assert payloads[1]["sampled"] is False


def test_structured_logger_preserves_standard_extra_formatting() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging_utils.StructuredLogger("uvicorn-compat")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info(
        "Started server process [%d]",
        148848,
        extra={"color_message": "Started server process [\x1b[36m%d\x1b[0m]"},
    )

    assert stream.getvalue().strip() == "Started server process [148848]"


def test_structured_logger_supports_custom_and_standard_kwargs() -> None:
    stream = io.StringIO()
    logger = logging_utils.StructuredLogger("mixed-kwargs")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(stream))

    logger.info("camera_init", device="0", width=640, stacklevel=1)

    assert stream.getvalue().strip() == "camera_init  device='0'  width=640"


def test_rotation_bounds_utf8_bytes_and_keeps_latest_five(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_LOG_MAX_BYTES", 128)
    path = tmp_path / "runtime.log"
    # Reopening the handler simulates restarts without resetting retention.
    for start in (0, 10):
        handler = logging_utils._BoundedFileHandler(path)
        try:
            for number in range(start, start + 10):
                record = logging.LogRecord(
                    "test", logging.INFO, __file__, 0,
                    f"{number:02d}:" + "相机" * 18, (), None,
                )
                handler.handle(record)
        finally:
            handler.close()
    files = [path] + [tmp_path / f"runtime.log.{i}" for i in range(1, 5)]
    assert set(tmp_path.iterdir()) == set(files)
    assert all(item.stat().st_size <= 128 for item in files)
    assert [item.read_text()[:2] for item in files] == ["19", "18", "17", "16", "15"]


def test_oversized_trace_stays_bounded_and_parseable(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_LOG_MAX_BYTES", 512)
    logging_utils.configure_event_trace(log_dir=str(tmp_path))
    try:
        logging_utils.vision_trace("large", data="相机" * 1000)
        path = tmp_path / "vision_trace_current.jsonl"
        assert path.stat().st_size <= 512
        payload = json.loads(path.read_text().removeprefix("VISION_TRACE "))
        assert payload["record"] == "log_record_omitted"
    finally:
        logging_utils.configure_event_trace(enabled=False)


def test_trace_retention_survives_reconfiguration(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_utils, "_LOG_MAX_BYTES", 512)
    try:
        for start in (0, 10):
            logging_utils.configure_event_trace(log_dir=str(tmp_path))
            for number in range(start, start + 10):
                logging_utils.vision_trace("test", number=number, data="相机" * 35)
        path = tmp_path / "vision_trace_current.jsonl"
        files = [path] + [tmp_path / f"{path.name}.{i}" for i in range(1, 5)]
        assert set(tmp_path.iterdir()) == set(files)
        assert all(item.stat().st_size <= 512 for item in files)
        payloads = [
            json.loads(item.read_text().removeprefix("VISION_TRACE "))
            for item in files
        ]
        assert [item["number"] for item in payloads] == [19, 18, 17, 16, 15]
    finally:
        logging_utils.configure_event_trace(enabled=False)


def test_runtime_and_trace_use_shared_rotation_policy(tmp_path, monkeypatch):
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    old_level = root.level
    monkeypatch.setattr(logging_utils, "_log_initialized", False)
    try:
        logging_utils.setup_logging(str(tmp_path), node="vision_interaction", console=False)
        logging_utils.configure_event_trace(log_dir=str(tmp_path))
        handlers = [h for h in root.handlers if h not in old_handlers]
        handlers.append(logging_utils._trace_handler)
        assert len(handlers) == 2
        for handler in handlers:
            assert handler.maxBytes == 20 * 1024 * 1024
            assert handler.backupCount == 4
        logging_utils.vision_trace("test", run_id="retained")
        assert "retained" in (tmp_path / "vision_interaction.log").read_text()
        assert "retained" in (tmp_path / "vision_trace_current.jsonl").read_text()
    finally:
        logging_utils.configure_event_trace(enabled=False)
        for handler in root.handlers[:]:
            if handler not in old_handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(old_level)
