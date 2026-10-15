"""Action consumer DDS test, using the robotics synthetic world fixture."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('rclpy')
pytest.importorskip('robot_local_motion_runtime')
sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'robotics/ros2/src/robot_local_motion/test'))
from test_task_transport import stack


def test_action_adapter_bridges_stamped_commands_through_selected_backend(stack):
    from types import SimpleNamespace
    from marsdog_action_executor.adapters.local_motion_adapter import LocalMotionAdapter
    server,world,_=stack;world.direct=False;world.freeze=False
    class Backend:
        last_error=''
        def __init__(self):self.prepared=self.finished=0;self.commands=[]
        def prepare_navigation(self):self.prepared+=1;return True
        def finish_navigation(self):self.finished+=1;return True
        def publish_velocity(self,command):
            self.commands.append(command)
            world.v,world.w=command.linear_x,command.angular_z
    backend=Backend();unit='ACT_NAV_WALK_RANDOM'
    adapter=LocalMotionAdapter(node=world,backend=backend,allowed_units=[unit])
    ctx=SimpleNamespace(params={'local_motion':{'unit_id':unit,'mode':'move',
        'goal':{'frame_id':'base_footprint','x':.5,'y':0,'yaw':0},
        'parameters':{'max_linear_speed':.3}}},metadata={})
    feedback=[]
    ctx.runtime_feedback=lambda *values:feedback.append(values)
    start=world.x
    try:
        result=adapter.execute_task({'unit_id':unit},ctx,12)
        assert result.success and result.metadata['stop_confirmed'],result
        assert backend.prepared==backend.finished==1
        assert any(c.linear_x>0 for c in backend.commands)
        assert all(abs(c.linear_x)<=.3+1e-6 for c in backend.commands)
        assert world.x-start>.25 and backend.commands[-1].is_zero
        assert not adapter.active
        assert feedback and any('local_motion:' in row[2] for row in feedback)
        ctx.params['local_motion']['parameters']['timeout_sec']=.2
        timeout_result=adapter.execute_task({'unit_id':unit},ctx,.2)
        assert timeout_result.timed_out and not timeout_result.canceled,timeout_result
        assert timeout_result.metadata['stop_confirmed']
        assert not adapter.active and backend.finished==2 and backend.commands[-1].is_zero
    finally:
        adapter.cancel_step();world.destroy_timer(adapter.timer);world.destroy_subscription(adapter.sub)
        adapter.client.client.destroy();world.direct=True
