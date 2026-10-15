"""Explicit scenario-selected approach backends; legacy routes are untouched."""
UNITS = frozenset({'ACT_INTERACT_APPROACH_VOICE_CALLER', 'ACT_APPROACH_VISUAL_TARGET',
                   'ACT_INTERACT_APPROACH_OWNER', 'ACT_INTERACT_APPROACH_OWNER_CLOSER',
                   'ACT_INTERACT_RETURN_OWNER'})


def request_for(raw):
    if not isinstance(raw, dict) or set(raw) != {'mode', 'unit_id'}:
        raise ValueError('approach_requires_mode_and_unit_id')
    if raw['mode'] not in ('visual', 'local_nav', 'map_nav'):
        raise ValueError('approach_invalid_mode')
    if raw['unit_id'] not in UNITS:
        raise ValueError('approach_unsupported_unit')
    return dict(raw)


def route_for(raw):
    request = request_for(raw)
    if request['mode'] != 'visual':
        return 'approach_navigation'
    return ('target_approach' if request['unit_id'] == 'ACT_INTERACT_APPROACH_VOICE_CALLER'
            else 'visual_target_approach')


def validate_plan(params, stages, adapters):
    navigation = adapters.get('approach_navigation')
    if getattr(navigation, 'recovery_required', False):
        return 'approach_operator_recovery_required'
    if 'approach' not in params:
        return ''
    if 'local_motion' in params:
        return 'approach_and_local_motion_conflict'
    try:
        request = request_for(params['approach'])
        present = {c if isinstance(c, str) else c.get('unit_id')
                   for stage in stages for c in stage.get('candidates', [])
                   if isinstance(c, (str, dict))}
        if request['unit_id'] not in present:
            return 'approach_unit_not_in_behavior_plan'
        if adapters.get(route_for(request)) is None:
            return 'approach_controller_unavailable'
        if request['mode'] == 'local_nav':
            local = adapters.get('local_motion')
            if local is None or not local.can_execute(request['unit_id']):
                return 'approach_local_controller_unavailable'
        return ''
    except (ValueError, TypeError) as exc:
        return str(exc)
