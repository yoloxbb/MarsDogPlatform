from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import unittest
import yaml

from marsdog_behavior.tactile_events import TactileEventConsumer
from bionic_dog_bt.drive_policy import resolve_drive
from bionic_dog_bt.blackboard import Blackboard
from marsdog_behavior.candidate_pool import CandidatePool

CONFIG=Path(__file__).resolve().parents[1]/'config/tactile_events.yaml'


class TactileDirectEvents(unittest.TestCase):
    def setUp(self):
        self.received=[];self.wall=100.0;self.mono=1.0
        self.config=yaml.safe_load(CONFIG.read_text())
        self.consumer=TactileEventConsumer(self.config,self.received.append,
                    wall_time=lambda:self.wall,monotonic=lambda:self.mono)
        self.event={'schema_version':'1.0','event_type':'EVT_TACTILE_HEAD_PET',
                    'timestamp':100.0,'source':'ONE1000','sensorType':'UWB_DISTANCE',
                    'touchState':'STARTED'}

    def test_presets_generate_direct_candidates_without_changing_input(self):
        for event in self.config['events']:
            with self.subTest(event=event):
                data={**self.event,'event_type':event};original=deepcopy(data)
                self.assertTrue(self.consumer.consume(data))
                c=self.received[-1]
                self.assertEqual(c.source,'touch_direct')
                self.assertEqual(resolve_drive(c.to_pool_dict()['params']).state_domain,'')
                self.assertEqual(data,original)

    def test_emotion_only_events_have_no_direct_reaction(self):
        self.assertFalse(self.consumer.consume({**self.event,'event_type':'EVT_TACTILE_BODY_STROKE'}))
        self.assertFalse(self.received)

    def test_duplicate_old_and_future_events_rejected(self):
        self.assertTrue(self.consumer.consume(self.event))
        self.assertFalse(self.consumer.consume(self.event))
        for stamp in [90.0,101.0,True,float('nan'),'100']:
            with self.subTest(stamp=stamp):
                self.assertFalse(self.consumer.consume({**self.event,'timestamp':stamp}))

    def test_cooldown_uses_monotonic_clock(self):
        self.assertTrue(self.consumer.consume(self.event))
        self.wall+=100
        self.assertFalse(self.consumer.consume({**self.event,'timestamp':self.wall}))
        self.mono+=5
        self.assertTrue(self.consumer.consume({**self.event,'timestamp':self.wall}))

    def test_release_and_invalid_envelopes_never_dispatch(self):
        for data in [None,[],{},'{bad',{'event_type':[]},
                     {**self.event,'touchState':'ENDED'},{**self.event,'schema_version':'2.0'},
                     {**self.event,'source':''}]:
            with self.subTest(data=data):self.assertFalse(self.consumer.consume(data))
        self.assertFalse(self.received)

    def test_disabled_profile_still_allows_external_emotion_consumer(self):
        cfg={**self.config,'enabled':False}
        consumer=TactileEventConsumer(cfg,self.received.append)
        self.assertFalse(consumer.consume(self.event))
        self.assertEqual(self.event['event_type'],'EVT_TACTILE_HEAD_PET')

    def test_ros_message_reaches_same_consumer_and_pool(self):
        import json
        pool=CandidatePool(wall_time=lambda:self.wall,monotonic=lambda:self.mono)
        consumer=TactileEventConsumer(self.config,lambda c:pool.add(**c.to_pool_dict()),
                    wall_time=lambda:self.wall,monotonic=lambda:self.mono)
        self.assertTrue(consumer.consume(SimpleNamespace(data=json.dumps(self.event))))
        row=pool.select_best(Blackboard())
        self.assertEqual(row['params']['source'],'touch_direct')
        self.assertEqual(row['params']['trigger_event'],'EVT_TACTILE_HEAD_PET')

    def test_priority_and_limits_checked_at_configuration_time(self):
        for key,bad in [('priority_level',2.1),('priority_level',0),('ttl_sec',0),
                        ('cooldown_sec',-1),('timeout_sec',float('inf'))]:
            cfg=deepcopy(self.config);cfg['events']['EVT_TACTILE_HEAD_PET'][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):
                TactileEventConsumer(cfg,self.received.append)


if __name__=='__main__':unittest.main()
