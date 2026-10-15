"""Sub-rank order must survive mapping, queuing and preemption unchanged."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from bionic_dog_bt.arbitration import candidate_priority_key, priority_key, priority_label, evaluate_preemption
from bionic_dog_bt.blackboard import Blackboard
from marsdog_behavior.behavior_selector import select_best_from_pool, evaluate_preemption as legacy_preempt
from marsdog_behavior.candidate_pool import CandidatePool
from marsdog_behavior.intent_mapper import BehaviorCandidate


class PriorityOrderContract(unittest.TestCase):
    def test_sublevels_are_integer_pairs_including_two_ten(self):
        candidates = [BehaviorCandidate(behavior_name=str(n), priority_level=2, sub_priority=n)
                      for n in (10, 2, 1)]
        self.assertEqual([c.sub_priority for c in sorted(candidates, key=lambda c:c.sort_key)], [1,2,10])
        self.assertEqual(priority_label(2, sub_priority=10), '2.10')

    def test_invalid_rank_is_rejected_before_pool_reservation(self):
        for field in ['priority_level','sub_priority','semantic_rank','modality_rank']:
            for bad in [2.1, 2.0, True, -1, '2.1', None, float('nan')]:
                with self.subTest(field=field,bad=bad):
                    pool=CandidatePool()
                    options={'priority_level':2,field:bad}
                    self.assertFalse(pool.add('reused',**options))
                    self.assertTrue(pool.add('reused',2))

    def test_candidate_pool_and_helper_use_same_full_order(self):
        candidates=[BehaviorCandidate(behavior_name='older',priority_level=2,created_at=10),
                    BehaviorCandidate(behavior_name='newer',priority_level=2,created_at=11)]
        rows=[c.to_pool_dict() for c in candidates]
        for c,row in zip(candidates,rows):
            self.assertEqual(c.sort_key,candidate_priority_key(row))
        pool=CandidatePool(wall_time=lambda:11)
        for row in rows:pool.add(**row)
        self.assertEqual(select_best_from_pool(rows,Blackboard())['behavior_name'],'newer')
        self.assertEqual(pool.select_best(Blackboard())['behavior_name'],'newer')

    def test_explicit_legacy_override_resolves_same_at_every_boundary(self):
        c=BehaviorCandidate(priority_level=2,sub_priority=9,params={'behavior_rank':1,'semantic_rank':0},intensity=None)
        row=c.to_pool_dict();before=deepcopy(row)
        self.assertEqual(c.sort_key,candidate_priority_key(row))
        self.assertEqual(c.sort_key[:4],(2,0,3,1))
        self.assertEqual(row,before)
        self.assertEqual(priority_label(2,c.params,sub_priority=9),'2.1')

    def test_sublevel_does_not_override_semantics_or_main_level(self):
        self.assertLess(priority_key(1,{'sub_priority':99}),priority_key(2,{'sub_priority':0}))
        self.assertLess(priority_key(2,{'semantic_rank':0,'sub_priority':99}),
                        priority_key(2,{'semantic_rank':1,'sub_priority':0}))

    def test_all_candidates_cooling_down_yields_none(self):
        b=Blackboard();b.set_cooldown('one',100)
        row=BehaviorCandidate(behavior_name='one',priority_level=2).to_pool_dict()
        self.assertIsNone(select_best_from_pool([row],b))

    def test_sublevel_preemption_still_requires_safe_feedback(self):
        for safe,allowed in [(False,False),(True,True)]:
            feedback=SimpleNamespace(status='RUNNING',safe_to_interrupt=safe)
            args=(2,10,'new',2,99,'safe_point',feedback)
            params={'active_params':{'sub_priority':1},'current_params':{'sub_priority':2}}
            self.assertEqual(evaluate_preemption(*args,**params)[0],allowed)
            self.assertEqual(legacy_preempt(*args[:-1],'old',feedback,**params)[0],allowed)

    def test_equal_key_keeps_existing_intensity_hysteresis(self):
        feedback=SimpleNamespace(status='RUNNING',safe_to_interrupt=True)
        self.assertFalse(evaluate_preemption(2,51,'new',2,50,'immediate',feedback)[0])


if __name__ == '__main__':unittest.main()
