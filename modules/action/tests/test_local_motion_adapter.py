from types import SimpleNamespace as NS
from marsdog_action_executor.adapters.local_motion_adapter import LocalMotionAdapter, LocalMotionOutcome
from marsdog_action_executor.stage_executor import StageExecutor
from marsdog_action_executor.local_motion_request import validate_plan

UNIT='ACT_INTERACT_FOLLOW_OWNER'


class Backend:
    def __init__(self):
        self.prepared=0; self.finished=0; self.commands=[]; self.last_error=''
    def prepare_navigation(self):
        self.prepared+=1
        return True
    def finish_navigation(self):
        self.finished+=1
        return True
    def publish_velocity(self,cmd):
        self.commands.append(cmd)


class Client:
    def __init__(self,outcome):
        self.outcome=outcome; self.jobs=[]; self.canceled=False
    def run(self,job,deadline,should_stop,accepted,feedback=None):
        self.jobs.append(job); accepted()
        return self.outcome
    def cancel(self):
        self.canceled=True
    def recover(self):
        return True


def setup(outcome):
    b=Backend(); c=Client(outcome)
    a=LocalMotionAdapter(backend=b,client=c,allowed_units=[UNIT])
    ctx=NS(params={'local_motion':{'unit_id':UNIT,'mode':'follow','target_id':'owner',
        'target_source':'uwb','parameters':{'timeout_sec':50,'desired_distance_m':1.4}}},metadata={})
    return a,b,c,ctx


def test_task_settings_and_budget_are_forwarded_without_mutating_context():
    a,b,c,ctx=setup(LocalMotionOutcome(success=True,metadata={'stop_confirmed':True}))
    assert a.execute_task({'unit_id':UNIT},ctx,20).success
    assert c.jobs[0]['parameters']['timeout_sec']==20
    assert c.jobs[0]['parameters']['desired_distance_m']==1.4
    assert ctx.params['local_motion']['parameters']['timeout_sec']==50
    assert not a.active and b.finished==1 and b.commands[-1].is_zero


def test_unknown_terminal_retains_ownership_and_requires_explicit_recovery():
    a,b,c,ctx=setup(LocalMotionOutcome(reason='terminal unknown',metadata={'recovery_required':True}))
    assert not a.execute_task({'unit_id':UNIT},ctx,20).success
    assert a.active and b.finished==0 and not a.forwarding
    assert not a.execute_task({'unit_id':UNIT},ctx,20).success
    assert len(c.jobs)==1
    assert a.recover() and not a.active and b.finished==1


def test_request_cannot_redirect_a_manipulation_unit():
    a,b,c,ctx=setup(LocalMotionOutcome(success=True))
    assert not a.execute_task({'unit_id':'ACT_OBJECT_FETCH'},ctx,20).success
    assert b.prepared==0 and not c.jobs


def test_old_route_is_default_and_override_selects_only_the_named_unit():
    e=object.__new__(StageExecutor)
    e._controller_routes={UNIT:'uwb_follow','ACT_UWB_RANDOM_ROAM':'uwb_roam'}
    ctx=NS(params={})
    assert e._route_for(UNIT,ctx)=='uwb_follow'
    ctx.params={'local_motion':{'unit_id':UNIT}}
    assert e._route_for(UNIT,ctx)=='local_motion'
    assert e._route_for('ACT_UWB_RANDOM_ROAM',ctx)=='uwb_roam'


def test_override_disabled_never_falls_back_to_old_controller():
    e=object.__new__(StageExecutor)
    e._controller_routes={UNIT:'uwb_follow'}
    e._controller_adapters={'uwb_follow':NS(can_execute=lambda _:True)}
    ctx=NS(params={'local_motion':{'unit_id':UNIT}},resolved_behavior_name='',current_stage='')
    assert not e._controller_candidate_available({'unit_id':UNIT},ctx)


def test_explicit_override_is_validated_before_any_stage_runs():
    a,_,_,ctx=setup(LocalMotionOutcome(success=True))
    stages=[{'candidates':[{'unit_id':UNIT}]}]
    assert validate_plan(ctx.params,stages,a)==''
    assert validate_plan(ctx.params,stages,None)=='local_motion_controller_unavailable'
    assert validate_plan(ctx.params,[],a)=='local_motion_unit_not_in_behavior_plan'
    assert validate_plan({'local_motion':{'unit_id':'ACT_OBJECT_FETCH'}},stages,a)
    assert validate_plan({},stages,None)==''
    a.active=True
    assert validate_plan({},stages,a)=='local_motion_recovery_required'


def test_malformed_unit_identity_fails_before_motion_preflight():
    assert validate_plan({'local_motion':{'unit_id':[],'mode':'move'}},[],None)=='local_motion_explicit_unit_required'


def test_backend_without_prepare_and_stop_confirmation_is_unavailable():
    adapter=LocalMotionAdapter(backend=NS(publish_velocity=lambda _:None),
        client=Client(LocalMotionOutcome(success=True)),allowed_units=[UNIT])
    assert not adapter.can_execute(UNIT)


def test_local_deadline_gates_velocity_while_cancel_result_is_pending():
    a,b,c,_=setup(LocalMotionOutcome(success=True))
    a.active=a.forwarding=True
    a.command_deadline=0
    a.command=NS(is_zero=False,linear_x=.3,linear_y=0,angular_z=0)
    a.command_at=__import__('time').monotonic()
    a.forward()
    assert c.canceled and not a.forwarding and b.commands[-1].is_zero
    assert a.active  # still owns the chassis until terminal stop confirmation
