"""Product dispositions and additive plans must agree; a decision is not acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from capability_decisions import validate_decisions
from capability_snapshot import backlog


class CapabilityDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / 'interfaces/naming/catalog.json').read_text(encoding='utf-8'))

    def test_all_legacy_gaps_have_explicit_dispositions(self):
        self.assertEqual(validate_decisions(self.catalog), [])
        entries = self.catalog['capability_decisions']['behaviors']
        self.assertEqual(sum(d['decision'] == 'implemented_preset' for d in entries.values()), 33)
        self.assertEqual(sum(d['decision'] == 'deferred_integration' for d in entries.values()), 16)

    def test_missing_removed_and_stale_decisions_fail_gate(self):
        for change in ('missing', 'stale', 'unrouted', 'unimplemented'):
            broken = deepcopy(self.catalog)
            entries = broken['capability_decisions']['behaviors']
            if change == 'missing': del entries['find_dad']
            if change == 'stale': broken['behaviors']['find_dad'] = []
            if change == 'unrouted': entries['absent'] = entries['find_dad']
            if change == 'unimplemented': del broken['behaviors']['dance']
            self.assertTrue(validate_decisions(broken), change)

    def test_decision_requires_reason_owner_and_evidence(self):
        for field, value in [('decision', 'PASS'), ('reason', ''), ('owner_roles', []),
                             ('required_evidence', [False]), ('completion_scope', 'task_complete')]:
            broken = deepcopy(self.catalog)
            broken['capability_decisions']['behaviors']['dance'][field] = value
            self.assertTrue(validate_decisions(broken), field)

    def test_deferred_backlog_keeps_dependency_details(self):
        value = {'capability_decisions': self.catalog['capability_decisions'],
                 'routes': [{'capability_id': 'test', 'missing_templates': ['find_dad']}],
                 'supplemental_routes': []}
        result = backlog(value)
        self.assertEqual(result['status'], 'BLOCKED_DEPENDENCIES')
        entry, = result['entries']
        self.assertEqual(entry['decision'], 'DEFERRED_INTEGRATION')
        self.assertIn('family_role_identity_binding', entry['behavior_decisions']['find_dad']['required_evidence'])
        self.assertNotIn('hardware_acceptance', entry)

    def test_unknown_gaps_still_require_a_decision(self):
        result = backlog({'routes': [{'capability_id': 'new', 'missing_templates': ['future']}],
                          'supplemental_routes': []})
        self.assertEqual(result['status'], 'PRODUCT_DECISIONS_PENDING')
        self.assertEqual(backlog({'routes': [], 'supplemental_routes': []})['status'], 'NO_MISSING_TEMPLATES')


if __name__ == '__main__': unittest.main()
