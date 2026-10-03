import logging
from marsdog_vision_interaction.utils import logging_utils


def test_vision_event_uses_canonical_logger_metadata(caplog):
    logging_utils.configure_event_trace(enabled=True, run_id="run-01", case_id="STOP-01-r1")
    with caplog.at_level(logging.INFO):
        logging_utils.vision_trace("event_publish", result="published",
                                   event_type="EVT_VISION_STOP_GESTURE", latency_ms=12.3)
    record = caplog.records[-1]
    assert record.getMessage() == ""
    assert record.marsdog_event == "vision.event.published"
    assert record.marsdog_fields["test_run_id"] == "run-01"
    assert record.marsdog_fields["case_id"] == "STOP-01-r1"
    assert record.marsdog_fields["event_type"] == "EVT_VISION_STOP_GESTURE"


def test_policy_configuration_never_creates_sink_or_global_logger_class(tmp_path, monkeypatch):
    from pathlib import Path
    original = logging.getLoggerClass()
    def forbidden(*args, **kwargs):
        raise AssertionError("Domain policy must not create files")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    logging_utils.configure_event_trace(enabled=False)
    logging_utils.vision_trace("runtime_start", result="ready")
    assert logging.getLoggerClass() is original


def test_continuous_timing_is_sampled_but_failures_are_not(caplog, monkeypatch):
    monkeypatch.setattr(logging_utils, "time_monotonic_ms", lambda: 1000.0)
    logging_utils.configure_event_trace(enabled=True, timing_interval_sec=5)
    with caplog.at_level(logging.INFO):
        assert logging_utils.vision_timing_trace(node="vision", module="pose", stage="inference", latency_ms=12.3456)
        assert not logging_utils.vision_timing_trace(node="vision", module="pose", stage="inference", latency_ms=13)
        assert logging_utils.vision_timing_trace(node="vision", module="pose", stage="inference", latency_ms=1, result="failure")
    rows = caplog.records
    assert len(rows) == 2
    assert rows[0].marsdog_kind == "metric"
    assert rows[0].marsdog_fields["latency_ms"] == 12.346
    assert rows[0].marsdog_fields["sampled"] is True
    assert rows[1].levelno == logging.WARNING
    assert rows[1].marsdog_fields["sampled"] is False


def test_third_party_standard_logging_is_unchanged(caplog):
    logger = logging.getLogger("third.party")
    with caplog.at_level(logging.INFO):
        logger.info("Started process [%d]", 42, extra={"color_message": "unmodified"})
    assert caplog.records[-1].message == "Started process [42]"
    assert caplog.records[-1].color_message == "unmodified"


def test_fields_and_message_are_separate(caplog):
    logger = logging_utils.get_logger("camera")
    with caplog.at_level(logging.INFO):
        logger.info("camera_init", device="0", width=640, stacklevel=1)
    record = caplog.records[-1]
    assert record.getMessage() == "camera_init"
    assert record.marsdog_fields == {"device": "0", "width": 640}


def test_suppression_is_debug_not_repeated_info(caplog):
    logging_utils.configure_event_trace(enabled=True)
    with caplog.at_level(logging.DEBUG):
        logging_utils.vision_trace("event_suppressed", reason_code="identity_not_confirmed")
    assert caplog.records[-1].levelno == logging.DEBUG
    assert caplog.records[-1].marsdog_event == "vision.event.suppressed"
