"""Logging policy tests for the production INFO trace."""

import json
import logging

from bionic_dog_bt.logger import BTLogger, LogEvent


def test_successful_relevance_check_is_debug(caplog):
    logger = BTLogger("bionic_dog_bt.test_logging.relevance")

    with caplog.at_level(logging.DEBUG, logger=logger.logger.name):
        logger.event(
            LogEvent.RELEVANCE_PASS,
            behavior_name="expressJoyAlone",
            triggered=True,
        )

    [record] = caplog.records
    assert record.levelno == logging.DEBUG
    assert record.marsdog_event == "behavior.internal.relevance.pass"


def test_internal_candidate_detail_is_debug_while_decision_lifecycle_has_own_event(caplog):
    logger = BTLogger("bionic_dog_bt.test_logging.lifecycle")

    with caplog.at_level(logging.DEBUG, logger=logger.logger.name):
        logger.event(
            LogEvent.CANDIDATE_INJECT,
            behavior_name="expressJoyAlone",
            priority_level=5,
        )

    [record] = caplog.records
    assert record.levelno == logging.DEBUG
    assert record.marsdog_event == "behavior.internal.candidate.inject"
