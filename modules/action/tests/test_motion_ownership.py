"""Application ownership, terminal truth and stale-callback regression tests."""
import asyncio
from dataclasses import fields
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest

from marsdog_action_executor.motion_ownership import MotionOwnership, unresolved_controllers
from marsdog_action_executor.goal_execution import on_execute
from marsdog_action_executor.goal_execution_ports import ExecutionRuntime, ExecutionPorts, MemoryExecutionState
from marsdog_action_executor.goal_lifecycle import on_goal, on_cancel


def test_cancel_ack_and_late_terminal_cannot_transfer_or_release_new_generation():
    owner = MotionOwnership()
    first = owner.reserve('same-id')
    assert owner.may_execute(first)
    assert owner.request_stop('same-id')
    assert not owner.may_execute(first)
    assert owner.reserve('new') is None
    assert owner.finish(first)
    second = owner.reserve('same-id')
    assert second.generation > first.generation
    assert not owner.finish(first)
    assert owner.current == second and owner.may_execute(second)


@pytest.mark.parametrize('name,field', [('local_motion','active'), ('waypoint','navigation_interlocked'),
    ('uwb_follow','recovery_required'), ('uwb_roam','recovery_required'),
    ('geometry_approach','recovery_required'), ('person_approach','recovery_required')])
def test_every_unresolved_controller_blocks_replacement_until_real_clear(name,field):
    controller = NS(**{field: True})
    owner = MotionOwnership(); first = owner.reserve('one')
    assert not owner.finish(first, unresolved_controllers({name:controller}))
    assert owner.reserve('two') is None
    setattr(controller, field, False)
    assert owner.reconcile(unresolved_controllers({name:controller}))
    assert owner.reserve('two')


def test_unknown_controller_state_is_not_idle():
    class Broken:
        @property
        def recovery_required(self): raise RuntimeError('disconnected')
    assert unresolved_controllers({'nav': Broken()}) == ('nav:state_unavailable',)


def test_cleanup_failure_is_not_automatically_reconciled():
    owner = MotionOwnership(); lease = owner.reserve('one')
    owner.finish(lease, ['cleanup_failed:operator_recovery_required'])
    assert not owner.reconcile(())
    assert owner.reserve('two') is None


def make_runtime(owner, lease, execute, *, stop=None, unresolved=()):
    values = {f.name: None for f in fields(ExecutionPorts)}
    values.update(behavior_execution_lock=threading.Lock(),
        goal_reservation_lock=threading.Lock(), lease_lock=threading.Lock(), lease_seen={},
        motion_ownership=owner, motion_lease_for=lambda h: lease, forget_motion_lease=Mock(),
        execute_behavior=execute, behavior_sounds=NS(stop=stop or (lambda:None)),
        unresolved_motion=lambda:unresolved)
    return ExecutionRuntime(MemoryExecutionState(reserved_goal_id='g'), ExecutionPorts(**values))


def goal():
    return NS(request=NS(goal_id='g', behavior_id='b', behavior_name='wait', priority_level=2),
        is_cancel_requested=False, abort=Mock(), canceled=Mock())


def test_cleanup_exception_unlocks_but_latches_unknown_stop():
    owner=MotionOwnership();lease=owner.reserve('g')
    async def execute(handle): return {'status':'SUCCESS'}
    def stop(): raise RuntimeError('sound transport failed')
    runtime=make_runtime(owner,lease,execute,stop=stop)
    with pytest.raises(RuntimeError,match='transport'):
        asyncio.run(on_execute(runtime, goal(), make_result=lambda *a,**k:k))
    assert not runtime.ports.behavior_execution_lock.locked()
    assert runtime.state.reserved_goal_id is None
    assert owner.current is None and not owner.reconcile(())


def test_emergency_revocation_before_execute_starts_no_plan():
    owner=MotionOwnership();lease=owner.reserve('g');owner.request_stop('g')
    execute=Mock()
    runtime=make_runtime(owner,lease,execute)
    result=asyncio.run(on_execute(runtime,goal(),make_result=lambda *a,**k:k))
    assert result['status']=='FAILED'
    execute.assert_not_called()


def test_late_cancel_for_reused_id_does_not_cancel_new_generation():
    owner=MotionOwnership();first=owner.reserve('g');old=goal();owner.finish(first)
    second=owner.reserve('g')
    node=NS(_motion_ownership=owner,_goal_motion_leases={id(old):first},
        _long_goal_id=None,get_logger=lambda:Mock(),_interrupt=Mock())
    response=NS(REJECT='reject',ACCEPT='accept')
    assert on_cancel(node,old,cancel_response=response)=='reject'
    node._interrupt.request_cancel.assert_not_called()
    assert owner.may_execute(second)


@pytest.mark.parametrize('attribute,field',[('_local_motion_adapter','active'),('_waypoint_nav_client','navigation_interlocked')])
def test_real_admission_rejects_local_or_waypoint_unknown_terminal(attribute,field):
    node=NS(get_logger=lambda:Mock(), **{attribute:NS(**{field:True})})
    request=NS(behavior_name='wait',goal_id='g',priority_level=1,params_json='{}',timeout_sec=10)
    assert on_goal(node,request,goal_response=NS(REJECT=False,ACCEPT=True)) is False


def test_execution_exception_stops_outlets_and_prevents_new_goal():
    owner=MotionOwnership();lease=owner.reserve('g');stops=[]
    async def execute(handle): raise ValueError('executor fault')
    runtime=make_runtime(owner,lease,execute)
    from dataclasses import replace
    runtime=replace(runtime,ports=replace(runtime.ports,stop_motion=lambda:stops.append('stop')))
    with pytest.raises(ValueError,match='executor fault'):
        asyncio.run(on_execute(runtime,goal(),make_result=lambda *a,**k:k))
    assert stops==['stop'] and not runtime.ports.behavior_execution_lock.locked()
    assert owner.reserve('replacement') is None


def test_parallel_goal_admission_reserves_only_one_owner():
    owner=MotionOwnership()
    node=NS(_motion_ownership=owner,_goal_motion_leases={},
        _acceptable_behaviors={'wait'},_goal_reservation_lock=threading.Lock(),
        _behavior_execution_lock=threading.Lock(),_reserved_goal_id=None,get_logger=lambda:Mock())
    start=threading.Barrier(3);results=[]
    def submit(gid):
        start.wait()
        request=NS(behavior_name='wait',goal_id=gid,priority_level=1,params_json='{}',timeout_sec=10)
        results.append((gid,on_goal(node,request,goal_response=NS(REJECT=False,ACCEPT=True))))
    threads=[threading.Thread(target=submit,args=(gid,)) for gid in ('a','b')]
    for thread in threads:thread.start()
    start.wait()
    for thread in threads:thread.join(3)
    accepted=[gid for gid,ok in results if ok]
    assert len(accepted)==1
    assert owner.current.goal_id==node._reserved_goal_id==accepted[0]
