"""Read-only configuration checks shared by the launcher and pure tests."""
import math
from .uwb_protocol import canonical_id


def validate_roles(owner, frisbee):
    owner, frisbee = canonical_id(owner), canonical_id(frisbee)
    if owner == frisbee:
        raise ValueError('owner_id and frisbee_id must be different')
    supported = {'0x87654322', '0x87654324'}
    if {owner, frisbee} != supported:
        raise ValueError('this deployment must assign the two verified IDs 0x87654322 and 0x87654324')
    return owner, frisbee


def validate_chassis(document):
    try:
        server = document['local_motion_server']['ros__parameters']
        planner = document['local_velocity_planner_node']['ros__parameters']
        minimum, decel = server['min_linear_speed'], server['target_braking_decel']
        values = (minimum, decel, planner['min_linear_speed'], planner['max_linear_decel'])
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError('measured chassis values must be finite and positive')
        if minimum > 1.0 or decel > 0.70 or minimum != planner['min_linear_speed'] or decel != planner['max_linear_decel']:
            raise ValueError('chassis values must agree between server and planner; limits are 1.0 m/s and 0.70 m/s^2')
        # The supplied file is a narrow override; it cannot disable strict arrival
        # or replace the isolated action/output/frame configuration.
        allowed_server = {'min_linear_speed', 'target_braking_decel', 'target_reaction_sec', 'target_position_margin_m'}
        allowed_planner = {'min_linear_speed', 'max_linear_decel'}
        if set(document) != {'local_motion_server', 'local_velocity_planner_node'} or set(server)-allowed_server or set(planner)-allowed_planner:
            raise ValueError('chassis_params_file may only override measured minimum speed and braking values')
        for key in ('target_reaction_sec', 'target_position_margin_m'):
            if key in server and (type(server[key]) not in (int, float) or not math.isfinite(server[key]) or server[key] < 0):
                raise ValueError('invalid '+key)
    except (KeyError, TypeError) as exc:
        raise ValueError('chassis_params_file must contain matching min_linear_speed and deceleration for both nodes') from exc
    return minimum, decel
