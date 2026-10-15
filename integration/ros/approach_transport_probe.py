"""Real DDS clients + test-only services/actions in a reserved localhost domain.

Depth, TF, Nav2, local planner and chassis are explicit fixtures. No hardware
node is started. Production Action adapters perform all requests and cleanup.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    assert os.environ.get('ROS_DOMAIN_ID') == '216'
    import rclpy
    from rclpy.action import ActionServer, CancelResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from marsdog_vision_interaction.srv import VisionTask
    from person_3d_localization.srv import LocateFromBbox
    from nav2_msgs.action import NavigateToPose
    from robot_local_motion.action import ExecuteLocalMotion
    from marsdog_action_executor.adapters import geometry_approach_transport as module
    from marsdog_action_executor.adapters.person_nav_approach_adapter import PersonNavApproachAdapter
    from marsdog_action_executor.adapters.local_motion_adapter import LocalMotionAdapter

    fixture = json.loads(args.fixture.read_text())
    rclpy.init()
    server = rclpy.create_node('approach_fixture_server')
    client = rclpy.create_node('approach_production_adapter_probe')
    group = ReentrantCallbackGroup()
    state = {'scenario': '', 'nav': 0, 'local': 0, 'geometry': 0, 'prepare': 0, 'finish': 0}
    geometry_seen = threading.Event(); geometry_done = threading.Event(); nav_seen = threading.Event()
    def vision(request, response):
        assert request.task_type == 'locate_person_geometry'
        assert json.loads(request.params_json)['target_id'] == fixture['target_id']
        payload = copy.deepcopy(fixture)
        if state['scenario'] == 'wrong_target': payload['target_id'] = 'wrong:human:1'
        response.success = True
        response.result_json = json.dumps(payload)
        return response
    def geometry(request, response):
        state['geometry'] += 1
        assert request.image_header.stamp.sec == 123 and request.image_header.stamp.nanosec == 250000000
        assert request.image_header.frame_id == 'camera_optical'
        assert [request.bbox.x_offset, request.bbox.y_offset, request.bbox.width, request.bbox.height] == [128, 48, 256, 384]
        assert request.stand_off_distance == 1.5
        geometry_seen.set()
        if state['scenario'] == 'cancel_localization': time.sleep(.3)
        response.success = state['scenario'] != 'no_depth'
        response.status = 0 if response.success else 1
        response.message = 'fixture'
        response.navigation_required = state['scenario'] != 'already_near'
        response.person_point.header.frame_id = 'map'
        response.person_point.point.x = 3.
        response.navigation_goal.header.frame_id = 'map'
        response.navigation_goal.pose.position.x = 1.5
        response.navigation_goal.pose.orientation.w = 1.
        geometry_done.set()
        return response
    def nav(handle):
        state['nav'] += 1
        assert handle.request.pose.header.frame_id == 'map'
        assert handle.request.pose.pose.position.x == 1.5
        nav_seen.set()
        if state['scenario'] == 'cancel_navigation':
            deadline = time.monotonic()+3
            while not handle.is_cancel_requested and time.monotonic() < deadline: time.sleep(.01)
            assert handle.is_cancel_requested
            handle.canceled()
        else: handle.succeed()
        return NavigateToPose.Result()
    def local(handle):
        state['local'] += 1
        assert handle.request.mode == 'move' and handle.request.goal.header.frame_id == 'map'
        assert handle.request.goal.pose.position.x == 1.5
        handle.succeed()
        return ExecuteLocalMotion.Result(outcome='SUCCEEDED', message='fixture',
            stop_confirmed=state['scenario'] != 'stop_unknown', effective_parameters_json='{}')
    services = [server.create_service(VisionTask, '/phase4/vision', vision, callback_group=group),
                server.create_service(LocateFromBbox, '/person_3d_localization/locate_from_bbox', geometry, callback_group=group)]
    actions = [ActionServer(server, NavigateToPose, '/phase4/nav', nav,
                   cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=group),
               ActionServer(server, ExecuteLocalMotion, '/phase4/local', local,
                   cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=group)]
    def prepare(): state['prepare'] += 1; return True
    def finish(): state['finish'] += 1; return True
    backend = SimpleNamespace(prepare_navigation=prepare, finish_navigation=finish, publish_velocity=lambda _: None)
    unit = 'ACT_INTERACT_APPROACH_VOICE_CALLER'
    local_adapter = LocalMotionAdapter(node=client, backend=backend, allowed_units=[unit],
        action_name='/phase4/local', command_topic='/phase4/command')
    transport = module.GeometryApproachTransport(client, vision_service='/phase4/vision', nav_action='/phase4/nav',
        local_adapter=local_adapter, server_timeout_sec=1.)
    adapter = PersonNavApproachAdapter(transport, lambda _: None, chassis_backend=backend, allow_bound_target=True)
    executor = MultiThreadedExecutor(num_threads=6); executor.add_node(server); executor.add_node(client)
    spin = threading.Thread(target=executor.spin, daemon=True); spin.start()
    results = []
    try:
        for scenario, mode, expected in [('map_success','map_nav',True),('local_success','local_nav',True),
                ('no_depth','map_nav',False),('wrong_target','map_nav',False),('already_near','map_nav',True),
                ('cancel_localization','map_nav',False),('cancel_navigation','map_nav',False),
                ('stop_unknown','local_nav',False)]:
            state['scenario'] = scenario
            before = dict(state)
            geometry_seen.clear(); geometry_done.clear(); nav_seen.clear()
            params = {'strict_target_lock': True, 'allow_target_switch': False,
                'wake_id': 'fixture-wake', 'interaction_id': 'fixture-interaction',
                'speaker_status': 'matched', 'speaker_role': 'owner', 'speaker_id': 'owner',
                'approach': {'mode': mode, 'unit_id': unit}}
            ctx = SimpleNamespace(params=params, target={'target_type': 'human', 'vision_epoch': 'contract',
                'target_id': fixture['target_id']}, metadata={}, report_runtime_feedback=lambda *a: None)
            cancel_thread = None
            if scenario.startswith('cancel_'):
                event = geometry_seen if scenario == 'cancel_localization' else nav_seen
                def cancel_when_seen():
                    if event.wait(3): adapter.cancel_task()
                cancel_thread = threading.Thread(target=cancel_when_seen); cancel_thread.start()
            outcome = adapter.execute_task({'unit_id': unit}, ctx, 4.)
            if cancel_thread: cancel_thread.join(4)
            if scenario == 'cancel_localization': assert geometry_done.wait(1)
            assert outcome.success is expected, (scenario, outcome)
            if scenario.startswith('cancel_'): assert outcome.canceled
            if scenario in ('no_depth','wrong_target','already_near','cancel_localization'):
                assert state['nav'] == before['nav'] and state['local'] == before['local']
            if scenario == 'local_success':
                assert state['prepare']-before['prepare'] == state['finish']-before['finish'] == 1
                assert state['nav'] == before['nav']
            if scenario == 'stop_unknown':
                assert local_adapter.active and adapter.recovery_required
                retry = adapter.execute_task({'unit_id': unit}, ctx, 1.)
                assert retry.reason == 'operator_recovery_required' and not retry.success
            results.append({'scenario': scenario, 'mode': mode, 'success': outcome.success,
                            'reason': outcome.reason, 'canceled': outcome.canceled})
        # Exercise the installed BT callback over the real tactile topic without
        # constructing a hardware node or dispatching any movement.
        from std_msgs.msg import String
        from ament_index_python.packages import get_package_share_directory
        from marsdog_behavior.ros_node import BehaviorTreeRosNode
        from marsdog_behavior.tactile_events import TactileEventConsumer
        from marsdog_behavior.candidate_pool import CandidatePool
        from bionic_dog_bt.blackboard import Blackboard
        pool = CandidatePool(wall_time=lambda: 100., monotonic=lambda: 1.)
        shell = SimpleNamespace(_candidate_pool=pool, _is_duplicate_or_running=lambda *a: False,
                                _logger=SimpleNamespace(debug=lambda *a: None))
        shell._tactile_events = TactileEventConsumer.from_file(
            Path(get_package_share_directory('marsdog_behavior'))/'config/tactile_events.yaml',
            lambda candidate: BehaviorTreeRosNode._add_candidate(shell, candidate),
            wall_time=lambda: 100., monotonic=lambda: 1.)
        tactile_seen = threading.Event()
        def consume(message):
            if BehaviorTreeRosNode._on_tactile_event_ros2(shell, message): tactile_seen.set()
        subscription = client.create_subscription(String, '/perception/tactile_event', consume, 10)
        publisher = server.create_publisher(String, '/perception/tactile_event', 10)
        deadline = time.monotonic()+3
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline: time.sleep(.02)
        publisher.publish(String(data=json.dumps({'schema_version': '1.0', 'timestamp': 100.,
            'event_type': 'EVT_TACTILE_HEAD_PET', 'source': 'fixture', 'sensorType': 'TOUCH', 'touchState': 'STARTED'})))
        assert tactile_seen.wait(2)
        selected = pool.select_best(Blackboard())
        assert selected['behavior_name'] == 'expressJoyAlone' and selected['params']['source'] == 'touch_direct'
        results.append({'scenario': 'tactile_dds_to_common_pool', 'source': selected['params']['source'],
                        'behavior': selected['behavior_name']})
        report = {'status': 'PASS', 'cases': results, 'counts': state,
            'scope': 'Real installed Action/BT adapters and DDS; camera, tactile sensor, depth/TF, planners and chassis are fixtures',
            'module_file': module.__file__, 'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report))
    finally:
        adapter.cancel_task()
        executor.shutdown(timeout_sec=2); spin.join(2)
        for action in actions: action.destroy()
        server.destroy_node(); client.destroy_node(); rclpy.shutdown()


if __name__ == '__main__': main()
