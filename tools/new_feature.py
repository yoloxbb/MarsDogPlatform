"""Scaffold a reviewable feature proposal against existing Action capabilities.

Drafts never activate production mappings. Generated module contract tests fail
until the owning modules implement the proposal; no placeholder passing tests.
"""
import argparse
import json
from pathlib import Path
import re
from runtime_environment import ROOT
from check_identifiers import CATALOG, check_freshness

REQUIRED_CASES = ("positive_command", "negated_command", "wrong_command_id",
                  "duplicate_event", "cancel_during_execution", "unsupported_capability")


def validate_proposal(proposal, catalog):
    if not isinstance(proposal, dict):
        return ["proposal must be an object"]
    errors = [key + " must be a string" for key in
              ("name", "phrase", "event", "command_id", "intent", "behavior")
              if not isinstance(proposal.get(key), str)]
    if errors:
        return errors
    if type(proposal.get("schema_version")) is not int or proposal.get("schema_version") != 1:
        errors.append("unsupported proposal schema")
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", str(proposal.get("name", ""))):
        errors.append("feature name must use lower_snake_case")
    for key, pattern in (("event", r"EVT_VOICE_COMMAND_[A-Z0-9_]+"),
                         ("command_id", r"CMD_[A-Z0-9_]+"),
                         ("intent", r"[a-z][a-z0-9_]*")):
        if not re.fullmatch(pattern, str(proposal.get(key, ""))):
            errors.append("invalid " + key)
    if not str(proposal.get("phrase", "")).strip():
        errors.append("phrase is required")
    if proposal.get("behavior") not in catalog["behaviors"]:
        errors.append("unknown Action template; implement and register capability first")
    if proposal.get("event") in {r["event"] for r in catalog["routes"] + catalog["voice_commands"]}:
        errors.append("event already exists; extend its owning definition instead of duplicating it")
    if proposal.get("command_id") in {r["command_id"] for r in catalog["voice_commands"]}:
        errors.append("command_id already exists")
    if proposal.get("intent") in catalog["pools"]:
        errors.append("intent already exists")
    return errors


def create(proposal, destination, catalog):
    errors = validate_proposal(proposal, catalog)
    if errors:
        raise ValueError("; ".join(errors))
    destination.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        (destination / name).write_text(value, encoding="utf-8")
    write("feature.json", json.dumps(proposal, ensure_ascii=False, indent=2) + "\n")
    fragments = {
        "status": "DRAFT_NOT_ACTIVATED",
        "destinations": {
            "voice_command": "modules/voice/config/command_catalog.yaml:commands",
            "behavior_event": "modules/behavior/config/event_intent_map.yaml:audio_direct",
            "intent_pool": "modules/behavior/config/intent_action_pool.yaml",
        },
        "voice_command": {"command_key": proposal["name"].upper(), "command_id": proposal["command_id"],
                          "event_type": proposal["event"], "phrases": [proposal["phrase"]],
                          "action_name": "ACT_" + proposal["event"].removeprefix("EVT_VOICE_COMMAND_"), "control": "DO", "core": False},
        "behavior_event": {proposal["event"]: {"category": "external_interaction", "intent": proposal["intent"],
                                             "expected_command_id": proposal["command_id"], "sub_priority": 1}},
        "intent_pool": {proposal["intent"]: {"candidates": [proposal["behavior"]]}},
    }
    write("config_fragments.json", json.dumps(fragments, ensure_ascii=False, indent=2) + "\n")
    acceptance = {"status": "NOT_RUN", "cases": [{"id": name, "status": "NOT_RUN"} for name in REQUIRED_CASES]}
    write("acceptance.json", json.dumps(acceptance, indent=2) + "\n")
    voice_test = '''from pathlib import Path
from marsdog_voice_interaction.core.command_lexicon import CommandLexicon

PHRASE = {phrase!r}
EVENT = {event!r}
COMMAND = {command!r}

def test_positive_phrase_keeps_explicit_execution_authority():
    match = CommandLexicon(Path.cwd() / "config/command_catalog.yaml").match(PHRASE)
    assert match is not None, "Implement the proposed phrase in Voice first"
    event = match.to_event(asr_text=PHRASE, language="zh")
    assert event["event_type"] == EVENT
    assert event["command_id"] == COMMAND
    assert event["should_trigger_behavior_tree"] is True
    assert event["is_executable"] is True

def test_negation_must_not_become_the_positive_action():
    match = CommandLexicon(Path.cwd() / "config/command_catalog.yaml").match("不要" + PHRASE)
    if match is not None:
        event = match.to_event(asr_text="不要" + PHRASE, language="zh")
        assert not (event["event_type"] == EVENT and event["is_executable"])
'''
    write("test_voice_contract.py", voice_test.format(phrase=proposal["phrase"], event=proposal["event"], command=proposal["command_id"]))
    wire = {"schema_version": 2, "event_type": proposal["event"], "specific_event_type": proposal["event"],
            "command_id": proposal["command_id"], "dispatch_role": "specific_command",
            "should_trigger_behavior_tree": True, "is_executable": True, "interaction_id": "feature-test-session",
            "utterance_id": "feature-test-turn", "intent_confidence": 1.0, "slots": []}
    behavior_test = '''from pathlib import Path
from marsdog_behavior.intent_mapper import IntentMapper

WIRE = {wire!r}
EXPECTED = {behavior!r}

def test_proposed_event_maps_to_the_selected_capability():
    mapper = IntentMapper(str(Path.cwd() / "config"))
    candidate = mapper.map_audio_event(WIRE["event_type"], dict(WIRE))
    assert candidate is not None, "Implement the proposed BT mapping first"
    assert candidate.behavior_name == EXPECTED
    assert candidate.params["interaction_id"] == WIRE["interaction_id"]

def test_wrong_command_identity_cannot_authorize_the_behavior():
    mapper = IntentMapper(str(Path.cwd() / "config"))
    wrong = dict(WIRE, command_id="CMD_UNRELATED_TEST")
    assert mapper.map_audio_event(WIRE["event_type"], wrong) is None
'''
    write("test_behavior_contract.py", behavior_test.format(wire=wire, behavior=proposal["behavior"]))
    action_test = '''from pathlib import Path
from marsdog_action_executor.config_loader import ConfigLoader

EXPECTED = {behavior!r}

def test_reused_template_references_declared_units():
    loader = ConfigLoader(Path.cwd() / "config")
    loader.load_all()
    template = loader.get_all_behavior_templates().get(EXPECTED)
    assert template is not None, "Missing selected Action template"
    assert template["stages"], "A declared name alone is not an implementation"
    for stage in template["stages"]:
        assert stage["candidates"]
        for candidate in stage["candidates"]:
            unit = candidate if isinstance(candidate, str) else candidate["unit_id"]
            assert unit in loader.action_catalog, "Undeclared Action unit: " + unit
'''
    write("test_action_contract.py", action_test.format(behavior=proposal["behavior"]))
    write("README.md", """# 功能草稿：""" + proposal["name"] + """

草稿尚未激活，也不表示设备可执行。config_fragments.json 是待评审片段，不能直接覆盖整份配置。

1. Voice：确认短语、否定表达、command_id、产品动作标签；补齐既有 command_key → NLU 协议映射及事件声明。
   检查词库来源行号、版本、扩展规则；若需要新模型意图，另行定义产品语义，本工具不改模型。
2. Behavior：添加精确事件映射、意图候选、必要的行为规格；明确目标、门限、TTL、超时和中断规则。
3. Action：本草稿复用已有模板，仍需用 capabilities 检查部署参数、Unit 门限和设备支持。
   新能力先在 Action 实现、测试并登记，禁止拿近似动作冒充新能力。
4. Emotion/Needs：只有明确需要结算时才更新结果映射与证据契约；不默认增加结算。
5. 分别在 modules/voice、modules/behavior、modules/action 下，用各自 .venv/bin/python -B -m pytest 运行本目录对应测试文件。
   Voice/BT 正向测试在功能未实现时应失败；Action 复用模板检查可先通过，不代表硬件可执行。不要改成 skip 或空断言。
6. 对照 acceptance.json 完成去重、执行中取消及能力拒绝场景；在已实现的功能上跑录音 trial。
7. 更新原配置后运行 check_identifiers.py --refresh --python modules/action/.venv/bin/python；
   再跑 dev.py check、受影响模块测试和 WORKFLOW.md 对应门禁。
8. 迁移历史资源保护与命名例外独立存在；真实语义变化必须明确评审，不能刷新旧基线掩盖差异。

生成器不写生产配置、不增加兼容豁免、不修改导航或模型。报告 NOT_RUN 不能当作验收通过。
""")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?")
    parser.add_argument("--phrase")
    parser.add_argument("--behavior")
    parser.add_argument("--event")
    parser.add_argument("--command-id")
    parser.add_argument("--output", type=Path, help="New draft directory; refuses to overwrite")
    parser.add_argument("--check", type=Path, help="Validate a draft feature.json without activating it")
    args = parser.parse_args(argv)
    catalog = json.loads((ROOT / CATALOG).read_text())
    check_freshness(catalog, ROOT)
    if args.check:
        proposal = json.loads(args.check.read_text())
        errors = validate_proposal(proposal, catalog)
        print(json.dumps({"status": "INVALID" if errors else "VALID_DRAFT_NOT_ACTIVATED", "errors": errors}))
        return int(bool(errors))
    if not args.name or not args.phrase or not args.behavior:
        parser.error("name, --phrase and --behavior are required")
    proposal = {"schema_version": 1, "name": args.name, "phrase": args.phrase, "behavior": args.behavior,
                "event": args.event or "EVT_VOICE_COMMAND_" + args.name.upper(),
                "command_id": args.command_id or "CMD_" + args.name.upper(),
                "intent": "command_" + args.name}
    destination = args.output or ROOT / "out/feature-drafts" / args.name
    try:
        create(proposal, destination, catalog)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({"status": "DRAFT_NOT_ACTIVATED", "directory": str(destination)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
