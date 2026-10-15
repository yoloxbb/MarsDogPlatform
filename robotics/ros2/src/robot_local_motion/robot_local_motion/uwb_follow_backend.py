"""Use the original public C++ follow core, including its per-goal brake latch."""
import ctypes
import math
from pathlib import Path

FIELDS = ('follow_distance', 'distance_deadband', 'angle_deadband', 'angle_reengage',
    'turn_response_delay', 'angular_braking_accel', 'angular_brake_release_speed',
    'angular_reverse_speed_threshold', 'linear_kp', 'angular_kp', 'min_linear_speed',
    'max_linear_speed', 'max_angular_speed', 'heading_slowdown_start', 'heading_stop_angle',
    'blind_rotation_max_speed', 'max_linear_accel', 'max_linear_decel', 'max_angular_accel')


def load_follow_profile():
    import yaml
    from ament_index_python.packages import get_package_share_directory
    path = Path(get_package_share_directory('go2_uwb_local_follow'))/'config/uwb_follow_only.yaml'
    config = yaml.safe_load(path.read_text())['uwb_follow_controller_node']['ros__parameters']
    return {key: config[key] for key in FIELDS}


class UwbFollowControl:
    def __init__(self, profile, distance, minimum, maximum, angular_maximum):
        from ament_index_python.packages import get_package_prefix
        self.config = {**profile, 'follow_distance': distance, 'min_linear_speed': minimum,
            'max_linear_speed': maximum, 'max_angular_speed': angular_maximum,
            'blind_rotation_max_speed': min(profile['blind_rotation_max_speed'], angular_maximum)}
        values = (ctypes.c_double*len(FIELDS))(*(self.config[key] for key in FIELDS))
        library = Path(get_package_prefix('robot_local_motion'))/'lib/libuwb_follow_binding.so'
        self.lib = ctypes.CDLL(str(library))
        self.lib.marsdog_uwb_follow_create.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int]
        self.lib.marsdog_uwb_follow_create.restype = ctypes.c_void_p
        self.lib.marsdog_uwb_follow_destroy.argtypes = [ctypes.c_void_p]
        self.lib.marsdog_uwb_follow_destroy.restype = None
        self.lib.marsdog_uwb_follow_reset.argtypes = [ctypes.c_void_p]
        self.lib.marsdog_uwb_follow_reset.restype = None
        self.lib.marsdog_uwb_follow_step.argtypes = [ctypes.c_void_p, ctypes.c_double,
            ctypes.c_double, ctypes.c_double, ctypes.POINTER(ctypes.c_double), ctypes.c_int]
        self.lib.marsdog_uwb_follow_step.restype = ctypes.c_int
        self.handle = self.lib.marsdog_uwb_follow_create(values, len(FIELDS))
        if not self.handle:
            raise ValueError('original UWB follow core rejected deployment configuration')

    def command(self, x, y, actual_angular):
        if not all(math.isfinite(v) for v in (x, y, actual_angular)):
            raise ValueError('non-finite UWB follow input')
        output = (ctypes.c_double*5)()
        if not self.lib.marsdog_uwb_follow_step(self.handle, x, y, actual_angular, output, 5):
            raise ValueError('UWB follow core command failed')
        return output[0], output[1]

    def reset(self):
        self.lib.marsdog_uwb_follow_reset(self.handle)

    def close(self):
        if getattr(self, 'handle', None):
            self.lib.marsdog_uwb_follow_destroy(self.handle)
            self.handle = None

    def __del__(self):
        self.close()
