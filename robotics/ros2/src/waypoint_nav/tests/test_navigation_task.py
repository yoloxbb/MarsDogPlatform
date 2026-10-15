"""Public navigation type executes the same durable admission/cancel tests."""
import json
import threading
import time
from test_wire_integration import WireIntegrationTests

class NavigationTaskTests(WireIntegrationTests):
    service_name = '/navigation/task'

    def test_action_public_client_keeps_real_cancel_terminal(self):
        from marsdog_action_executor.adapters.waypoint_nav_adapter import Ros2WaypointNavClient
        client = Ros2WaypointNavClient(self.client_node, service_name=self.service_name)
        outcomes=[]
        worker=threading.Thread(target=lambda:outcomes.append(client('action:public:1','A',10.0)))
        worker.start()
        try:
            self.assertTrue(self.goal_started.wait(5))
            client.cancel_navigation()
            worker.join(8)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes,[False])
            self.assertTrue(client.last_outcome.terminal_confirmed)
            self.assertEqual(client.last_outcome.state,'INTERRUPTED')
            self.assertEqual(self.goal_count,1)
        finally:
            client.cancel_navigation()
            worker.join(10)

class CanonicalEndpointTests(WireIntegrationTests):
    def test_single_endpoint_rejects_duplicates_and_retains_results(self):
        from marsdog_interfaces.srv import NavigationTask
        endpoints = dict(self.client_node.get_service_names_and_types())
        self.assertEqual(endpoints['/navigation/task'], ['marsdog_interfaces/srv/NavigationTask'])
        self.assertFalse(any(name.startswith('/waypoint_nav/') for name in endpoints))
        self.assertFalse(self.dispatcher.has_parameter('enable_navigation_task'))
        self.assertFalse(self.dispatcher.has_parameter('enable_legacy_voice_task'))
        response,body=self._call('action:canonical:1','goto_place',
            {'place':'A','timeout_sec':30.0,'preempt':False,'terminal_retention_sec':86400})
        self.assertTrue(response.success)
        self.assertTrue(self.goal_started.wait(5))
        first_client=self.client
        self.client=self.client_node.create_client(NavigationTask,'/navigation/task')
        self.kind=NavigationTask
        self.assertTrue(self.client.wait_for_service(timeout_sec=5))
        response,body=self._call('action:canonical:1','goto_place',
            {'place':'A','timeout_sec':30.0,'preempt':False,'terminal_retention_sec':86400})
        self.assertFalse(response.success)
        self.assertEqual(body['code'],'DUPLICATE_TASK_ID')
        response,body=self._call('cancel:canonical:1','cancel',{'target_task_id':'action:canonical:1'})
        self.assertTrue(response.success)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            response,body=self._call('query:canonical:'+str(time.time_ns()),'query',{'target_task_id':'action:canonical:1'})
            if body['status']['state']=='INTERRUPTED':break
            time.sleep(.05)
        self.assertEqual(body['status']['state'],'INTERRUPTED')
        self.assertEqual(self.goal_count,1)
        self.client_node.destroy_client(first_client)

# Do not collect the imported base class twice.
del WireIntegrationTests
