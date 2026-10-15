"""Exact tactile event mappings into the common behavior candidate pipeline.

Emotion consumes the same perception topic independently. This component never
updates emotion values or decides that a state threshold has been reached.
"""
from collections import OrderedDict
import json
import math
from pathlib import Path
import threading
import time

import yaml

from bionic_dog_bt.arbitration import priority_key
from .intent_mapper import BehaviorCandidate


class TactileEventConsumer:
    def __init__(self, config, enqueue, *, wall_time=time.time, monotonic=time.monotonic):
        self._config = self._validate(config)
        self._enqueue = enqueue
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._seen = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path, enqueue, **clocks):
        return cls(yaml.safe_load(Path(path).read_text(encoding='utf-8')), enqueue, **clocks)

    @staticmethod
    def _validate(config):
        if not isinstance(config, dict) or type(config.get('enabled')) is not bool:
            raise ValueError('tactile enabled must be boolean')
        result = dict(config)
        for name, default in [('max_age_sec', 2.0), ('future_tolerance_sec', 0.5)]:
            value = config.get(name, default)
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid tactile '+name)
            result[name] = float(value)
        if not isinstance(config.get('events'), dict):
            raise ValueError('tactile events must be an object')
        result['events'] = {}
        for event, raw in config['events'].items():
            if not isinstance(event, str) or not event.startswith('EVT_TACTILE_') or not isinstance(raw, dict):
                raise ValueError('invalid tactile event mapping')
            item = dict(raw)
            if not isinstance(item.get('behavior_name'), str) or not item['behavior_name'].strip():
                raise ValueError('tactile behavior_name required')
            if item.get('interrupt_policy') not in {'safe_point','immediate','non_interruptible'}:
                raise ValueError('invalid tactile interrupt policy')
            ranks = priority_key(item.get('priority_level',1), item)
            if not 1 <= ranks[0] <= 6:
                raise ValueError('tactile presets must not claim the emergency level')
            for name in ['ttl_sec','timeout_sec','cooldown_sec']:
                v=item.get(name)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
                    raise ValueError('invalid tactile '+name)
            result['events'][event]=item
        return result

    def consume(self, message) -> bool:
        raw=getattr(message,'data',message)
        try:
            data=json.loads(raw) if isinstance(raw,str) else raw
        except (ValueError,TypeError):
            return False
        if not self._config['enabled'] or not isinstance(data,dict):
            return False
        if data.get('schema_version') != '1.0' or data.get('touchState') != 'STARTED':
            return False
        event=data.get('event_type')
        if not isinstance(event,str):return False
        entry=self._config['events'].get(event)
        if entry is None:return False
        source=data.get('source');sensor=data.get('sensorType')
        if any(not isinstance(v,str) or not v.strip() or len(v)>128 for v in [source,sensor]):
            return False
        stamp=data.get('timestamp')
        if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp):
            return False
        age=self._wall_time()-stamp
        if age>min(self._config['max_age_sec'],entry['ttl_sec']) or age < -self._config['future_tolerance_sec']:
            return False
        identity=(source,sensor,str(data.get('anchorMacId','')),str(data.get('beaconId','')),event)
        now=self._monotonic()
        with self._lock:
            prior=self._seen.get(identity)
            if prior is not None and (stamp<=prior[0] or now-prior[1]<entry['cooldown_sec']):
                return False
            self._seen[identity]=(stamp,now)
            self._seen.move_to_end(identity)
            while len(self._seen)>256:self._seen.popitem(last=False)
        candidate=BehaviorCandidate(
            behavior_name=entry['behavior_name'],source='touch_direct',trigger_event=event,
            priority_level=entry.get('priority_level',1),sub_priority=entry.get('sub_priority',0),
            semantic_rank=entry.get('semantic_rank',3),modality_rank=entry.get('modality_rank',3),
            intensity=50.0,interrupt_policy=entry['interrupt_policy'],ttl_sec=entry['ttl_sec'],
            timeout_sec=entry['timeout_sec'],cooldown_sec=entry['cooldown_sec'],created_at=float(stamp),
            params={'tactile_source':source,'tactile_sensor_type':sensor,'tactile_timestamp':stamp},
        )
        self._enqueue(candidate)
        return True
