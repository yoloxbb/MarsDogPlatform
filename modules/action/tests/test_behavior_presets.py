"""Exercise actual preset plans through StageExecutor, including failure and cancel."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
import shutil
import time
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from marsdog_action_executor.behavior_presets import read_presets_yaml, validate_presets
from marsdog_action_executor.behavior_resolver import BehaviorResolver
from marsdog_action_executor.config_loader import ConfigLoader, ConfigurationError
from marsdog_action_executor.execution_context import ExecutionContext
from marsdog_action_executor.result_evaluator import ResultEvaluator
from marsdog_action_executor.stage_executor import StageExecutor

CONFIG = Path(__file__).resolve().parents[1] / 'config'
RAW = read_presets_yaml((CONFIG / 'behavior_presets.yaml').read_text(encoding='utf-8'))['behaviors']


@pytest.fixture(scope='module')
def loader():
    value = ConfigLoader(CONFIG)
    value.load_all()
    return value


def execute(loader, name, mode):
    template = loader.get_behavior_template(name)
    ctx = ExecutionContext.from_goal(name, {})
    BehaviorResolver(loader.get_behavior_names()).resolve(ctx)
    ctx.runtime_deadline_monotonic = time.monotonic() + template['runtime_budget_sec']
    adapter = Mock()
    adapter.can_execute.return_value = True
    adapter.last_error = 'fixture_failure'
    stage = StageExecutor(action_catalog=loader.action_catalog,
                          controller_routes=loader.get_controller_routes('lite3'),
                          controller_adapters={} if mode == 'missing' else {'lite3': adapter})
    def perform(unit, context, duration):
        assert 0 < duration <= loader.action_catalog[unit['unit_id']]['timeout_sec']
        if mode == 'cancel_during':
            stage._interrupt.request_cancel()
        return mode != 'failure'
    adapter.execute_step.side_effect = perform
    if mode == 'cancel_before':
        stage._interrupt.request_cancel()
    if mode == 'timeout':
        ctx.runtime_deadline_monotonic = time.monotonic() - 1
    outcomes = {}
    for row in template['stages']:
        result = stage.execute_stage(row, ctx)
        outcomes[row['stage_id']] = result.success
        if not result.success:
            break
    return ResultEvaluator().evaluate(ctx, outcomes, template['success_condition']), ctx, adapter


@pytest.mark.parametrize('name', sorted(RAW))
def test_required_expression_stages_execute_in_order(loader, name):
    result, ctx, adapter = execute(loader, name, 'success')
    assert result.success
    assert ctx.executed_units == [s['candidates'][0]['unit_id'] for s in RAW[name]['stages']]
    assert adapter.execute_step.call_count == len(RAW[name]['stages'])


@pytest.mark.parametrize('mode', ['failure', 'missing', 'cancel_before', 'cancel_during', 'timeout'])
@pytest.mark.parametrize('name', sorted(RAW))
def test_incomplete_expression_never_reports_success(loader, name, mode):
    result, ctx, adapter = execute(loader, name, mode)
    assert not result.success
    assert not ctx.completed_stages
    assert not ctx.executed_units
    if mode in ('missing', 'cancel_before', 'timeout'):
        adapter.execute_step.assert_not_called()
    else:
        adapter.execute_step.assert_called_once()
    if mode.startswith('cancel'):
        assert result.status == 'canceled'


@pytest.mark.parametrize('field,value', [('required', False), ('failure_policy', 'skip_stage'),
                                      ('selection_policy', 'sequence'), ('order', True),
                                      ('candidates', []), ('candidates', [{'unit_id': 'absent'}])])
def test_preset_cannot_turn_missing_required_work_into_success(loader, field, value):
    presets = deepcopy(RAW)
    presets['dance']['stages'][0][field] = value
    assert validate_presets(presets, {}, loader.action_catalog)


def test_preset_scope_budget_identity_and_version_are_validated(loader):
    for field, value in [('completion_scope', 'task_complete'), ('runtime_budget_sec', float('nan')),
                         ('runtime_budget_sec', True), ('runtime_budget_sec', 1),
                         ('behavior_name', 'different'), ('preset_version', True), ('description', '')]:
        presets = deepcopy(RAW)
        presets['dance'][field] = value
        assert validate_presets(presets, {}, loader.action_catalog), field
    assert validate_presets(RAW, {'dance': {}}, loader.action_catalog)


def test_loader_rejects_collision_and_duplicate_yaml_before_execution(tmp_path):
    shutil.copytree(CONFIG, tmp_path / 'config')
    file = tmp_path / 'config/behavior_presets.yaml'
    file.write_text('behaviors:\n  sit_down: {}\n')
    with pytest.raises(ConfigurationError, match='cannot override'):
        ConfigLoader(file.parent).load_all()
    file.write_text('behaviors:\n  dance: {}\n  dance: {}\n')
    with pytest.raises(ConfigurationError, match='duplicate preset YAML key'):
        ConfigLoader(file.parent).load_all()


def test_optional_legacy_folder_and_reload_do_not_retain_removed_presets(tmp_path):
    shutil.copytree(CONFIG, tmp_path / 'config')
    config = ConfigLoader(tmp_path / 'config'); config.load_all()
    assert config.get_behavior_template('dance')
    (tmp_path / 'config/behavior_presets.yaml').unlink()
    config.load_all()
    assert config.get_behavior_template('dance') is None
    assert config.get_behavior_template('sit_down')


def test_loaded_templates_do_not_share_mutable_preset_objects(loader):
    preset = loader.behavior_presets['dance']
    runtime = loader.get_behavior_template('dance')
    assert preset == runtime and preset is not runtime
    assert preset['stages'][0] is not runtime['stages'][0]


@pytest.mark.parametrize('policy', ['random_one', 'sequence', 'fixed', 'loop_random'])
def test_cancel_at_boundary_never_starts_optional_stationary_stage(loader, policy):
    stage = StageExecutor()
    stage._apply_stage_motion_state = Mock()
    stage._execute_unit = Mock(return_value=True)
    ctx = ExecutionContext.from_goal('probe', {})
    ctx.cancel_requested = True
    result = stage.execute_stage({'stage_id': 'next', 'selection_policy': policy,
                                  'required': False, 'motion_state': 'stationary',
                                  'candidates': [{'unit_id': 'ACT_BASIC_WAIT'}]}, ctx)
    assert not result.success
    stage._execute_unit.assert_not_called()
    stage._apply_stage_motion_state.assert_not_called()


@pytest.mark.parametrize('mode', ['success', 'failure', 'cancel_during'])
def test_goal_pipeline_returns_expression_scope_and_real_terminal(loader, mode):
    from marsdog_action_executor.goal_execution import execute_behavior
    from marsdog_action_executor.goal_execution_ports import ExecutionRuntime, ExecutionPorts, MemoryExecutionState
    from dataclasses import fields
    from marsdog_action_executor.goal_parser import GoalParser
    from marsdog_action_executor.interrupt_manager import InterruptManager
    from marsdog_action_executor.posture_manager import PostureManager
    interrupt = InterruptManager()
    adapter = Mock()
    adapter.can_execute.return_value = True
    adapter.last_error = 'fixture_failure'
    def perform(*args):
        if mode == 'cancel_during': interrupt.request_cancel()
        return mode != 'failure'
    adapter.execute_step.side_effect = perform
    routes = loader.get_controller_routes('lite3')
    sounds = SimpleNamespace(apply_control_behavior=lambda name: False,
                             play_for=lambda name: None, stage_sound=lambda *args: nullcontext())
    node = SimpleNamespace(_config=loader, _goal_parser=GoalParser(),
        _behavior_resolver=BehaviorResolver(loader.get_behavior_names()),
        _controller_routes=routes, _interrupt=interrupt, _posture=PostureManager(),
        _mobility_adapter=None, _behavior_sounds=sounds, _result_evaluator=ResultEvaluator(),
        _debug=Mock(), _publish_feedback=Mock(), get_logger=lambda: Mock())
    node._stage_executor = StageExecutor(action_catalog=loader.action_catalog,
        controller_routes=routes, controller_adapters={'lite3': adapter}, interrupt_manager=interrupt)
    goal = SimpleNamespace(request=SimpleNamespace(goal_id='g1', behavior_id='b1',
        behavior_name='dance', timeout_sec=25, params_json='{}'),
        is_cancel_requested=False, succeed=Mock(), canceled=Mock(), abort=Mock())
    deps = {f.name: None for f in fields(ExecutionPorts)}
    deps.update({key.lstrip('_'): value for key, value in vars(node).items()})
    deps['approach_adapters'] = {}
    runtime = ExecutionRuntime(MemoryExecutionState(), ExecutionPorts(**deps))
    result = asyncio.run(execute_behavior(runtime, goal, make_result=lambda *args, **kw: kw))
    assert result['metadata'] == {'completion_scope': 'expression_only', 'preset_version': 1}
    if mode == 'success':
        goal.succeed.assert_called_once()
        assert result['status'] == 'SUCCESS'
        assert adapter.execute_step.call_count == 2
    else:
        goal.succeed.assert_not_called()
        adapter.execute_step.assert_called_once()
        if mode == 'cancel_during':
            goal.canceled.assert_called_once()
            assert result['status'] == 'CANCELED'
        else:
            goal.abort.assert_called_once()
            assert result['status'] != 'SUCCESS'
