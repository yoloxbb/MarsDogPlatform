"""The BT budget covers additive expressions, which must not settle internal needs."""
from pathlib import Path
import pytest
import yaml

from marsdog_behavior.result_event_mapper import ResultEventMapper
from marsdog_behavior.intent_mapper import IntentMapper
from bionic_dog_bt.drive_policy import resolve_drive

ROOT = Path(__file__).resolve().parents[3]
PRESETS = yaml.safe_load((ROOT / 'modules/action/config/behavior_presets.yaml').read_text(encoding='utf-8'))['behaviors']
BEHAVIORS = yaml.safe_load((ROOT / 'modules/behavior/config/behaviors.yaml').read_text(encoding='utf-8'))['behaviors']
EVENTS = yaml.safe_load((ROOT / 'modules/behavior/config/event_intent_map.yaml').read_text(encoding='utf-8'))['audio_direct']
POOLS = yaml.safe_load((ROOT / 'modules/behavior/config/intent_action_pool.yaml').read_text(encoding='utf-8'))


@pytest.mark.parametrize('name', sorted(PRESETS))
def test_expression_goal_budget_matches_action_plan(name):
    assert BEHAVIORS[name]['timeout_sec'] >= PRESETS[name]['runtime_budget_sec']
    assert BEHAVIORS[name]['action_sequence'] == []


@pytest.mark.parametrize('name', sorted(PRESETS))
def test_expression_results_never_reduce_internal_needs(name):
    mapper = ResultEventMapper()
    assert mapper.build_started_event(name) is None
    for status in ('SUCCESS', 'FAILED', 'CANCELED', 'TIMEOUT'):
        assert mapper.build_result_event(name, status) is None


@pytest.mark.parametrize('name', sorted(PRESETS))
def test_real_voice_candidate_keeps_identity_drive_and_final_budget(name):
    mapper = IntentMapper(str(ROOT / 'modules/behavior/config'))
    rows = [(event, row) for event, row in EVENTS.items()
            if name in POOLS[row['intent']]['candidates']]
    assert rows
    for event, row in rows:
        candidate = mapper.map_audio_event(event, {
            'schema_version': 2, 'event_type': event, 'specific_event_type': event,
            'command_id': row['expected_command_id'], 'dispatch_role': 'specific_command',
            'should_trigger_behavior_tree': True, 'interaction_id': 'session-1',
            'utterance_id': name, 'slots': []})
        assert candidate is not None
        sent = candidate.to_pool_dict()
        assert candidate.behavior_name == name
        assert sent['timeout_sec'] >= PRESETS[name]['runtime_budget_sec']
        assert sent['params']['trigger_event'] == event
        assert sent['params']['source'] == 'audio_direct'
        assert resolve_drive(sent['params']).state_domain == ''
