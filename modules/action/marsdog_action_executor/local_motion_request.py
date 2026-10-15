"""ROS-independent shape validation for an explicit local movement override."""
import math

MOVEMENT_UNITS = frozenset({
    'ACT_INTERACT_APPROACH_VOICE_CALLER',
    'ACT_INTERACT_FOLLOW_OWNER', 'ACT_INTERACT_APPROACH_OWNER',
    'ACT_INTERACT_APPROACH_OWNER_CLOSER', 'ACT_INTERACT_RETURN_OWNER',
    'ACT_APPROACH_VISUAL_TARGET', 'ACT_UWB_RANDOM_ROAM',
    'ACT_NAV_WALK_RANDOM', 'ACT_CIRCLE_AROUND',
})


def request_for(raw, unit_id, allowed_units):
    if (not isinstance(raw, dict) or not isinstance(unit_id, str) or
            raw.get('unit_id') != unit_id or unit_id not in allowed_units):
        raise ValueError('local_motion_explicit_unit_required')
    if set(raw)-{'unit_id','mode','goal','target_id','target_source','parameters'}:
        raise ValueError('local_motion_unknown_request_field')
    if raw.get('mode') not in ('move','approach','follow','orbit','explore','turn'):
        raise ValueError('local_motion_invalid_mode')
    if any(not isinstance(raw.get(k,''),str) for k in ('target_id','target_source')):
        raise ValueError('local_motion_target_identity_must_be_string')
    settings = raw.get('parameters', {})
    if not isinstance(settings,dict):
        raise ValueError('local_motion_parameters_must_be_object')
    goal = raw.get('goal', {})
    if not isinstance(goal,dict) or set(goal)-{'frame_id','x','y','yaw'}:
        raise ValueError('local_motion_invalid_goal_fields')
    if not isinstance(goal.get('frame_id',''),str):
        raise ValueError('local_motion_goal_frame_must_be_string')
    for key in ('x','y','yaw'):
        value=goal.get(key,0.0)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not -1e6 <= value <= 1e6 or not math.isfinite(value):
            raise ValueError('local_motion_invalid_goal_coordinate')
    target_mode = raw['mode'] in ('approach','follow','orbit') or (raw['mode']=='explore' and settings.get('center_mode')=='target')
    if target_mode and (not raw.get('target_id') or not raw.get('target_source')):
        raise ValueError('local_motion_target_identity_required')
    if (raw['mode'] in ('move','turn') or settings.get('center_mode')=='goal') and not goal.get('frame_id'):
        raise ValueError('local_motion_fixed_goal_frame_required')
    return {**raw,'parameters':dict(settings),'goal':dict(goal)}


def validate_plan(params, stages, adapter):
    if bool(getattr(adapter,'active',False)):
        return 'local_motion_recovery_required'
    if 'local_motion' not in params:
        return ''
    raw=params['local_motion']
    try:
        unit=raw.get('unit_id') if isinstance(raw,dict) else ''
        request_for(raw,unit,MOVEMENT_UNITS)
        if adapter is None or not adapter.can_execute(unit):
            return 'local_motion_controller_unavailable'
        present={c if isinstance(c,str) else c.get('unit_id') for stage in stages
                 for c in stage.get('candidates',[]) if isinstance(c,(str,dict))}
        if unit not in present:
            return 'local_motion_unit_not_in_behavior_plan'
        return ''
    except ValueError as exc:
        return str(exc)
