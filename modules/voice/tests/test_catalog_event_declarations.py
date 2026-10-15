"""Catalog event identity is explicitly declared, independent of product labels."""
from pathlib import Path

import pytest
import yaml

from marsdog_voice_interaction.core.command_lexicon import CommandLexicon
from marsdog_voice_interaction.messages import voice_event_types


CATALOG_PATH = Path(__file__).resolve().parents[1] / "config/command_catalog.yaml"


def test_all_catalog_events_have_exact_declarations():
    catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    for command in catalog["commands"]:
        event = command["event_type"]
        assert getattr(voice_event_types, event, None) == event


@pytest.mark.parametrize("product_action_label", ["ACT_UNDECLARED_TEST", "ACT_PRODUCT_LABEL"])
def test_product_label_cannot_declare_an_event(tmp_path, product_action_label):
    catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    command = catalog["commands"][0]
    command["event_type"] = "EVT_VOICE_COMMAND_UNDECLARED_TEST"
    command["action_name"] = product_action_label
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared event_type"):
        CommandLexicon(path)


def test_declared_event_and_product_label_are_independent(tmp_path):
    catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    command = next(item for item in catalog["commands"] if item["command_key"] == "EAT_MEAL")
    command["action_name"] = "ACT_PRODUCT_LABEL"
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    match = CommandLexicon(path).get_command("EAT_MEAL")
    assert match.event_type == command["event_type"]
    assert match.command_id == command["command_id"]
    assert match.action_name == "ACT_PRODUCT_LABEL"
    event = match.to_event(asr_text=command["phrases"][0], language="zh")
    assert event["event_type"] == command["event_type"]
    assert {slot["key"]: slot["value"] for slot in event["slots"]}["action_name"] == "ACT_PRODUCT_LABEL"
