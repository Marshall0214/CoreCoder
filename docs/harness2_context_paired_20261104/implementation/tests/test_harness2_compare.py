"""Predeclared paired analysis must keep failures and unknown usage visible."""
import unittest

from integrations.harness2_compare import SCHEDULE, config, summarize


class ComparisonTests(unittest.TestCase):
    def test_only_one_switch_changes(self):
        a,b=config('control'),config('deduplicate')
        self.assertEqual([key for key in a if a[key]!=b[key]],['deduplicate_reads'])
        with self.assertRaises(ValueError):
            config('best')

    def test_schedule_has_three_complete_pairs_and_alternating_order(self):
        self.assertEqual(len(SCHEDULE),6)
        for pair in (1,2,3):
            self.assertEqual({variant for number,variant in SCHEDULE if number==pair},{'control','deduplicate'})
        self.assertEqual(SCHEDULE[2],(2,'deduplicate'))

    def test_paired_summary_does_not_turn_unknown_usage_into_zero(self):
        common={'pair':1,'nonempty_patch':False,'target_passed':False,'controls_passed':True,
                'calls':2,'agent_seconds':1,'tool_executions':1,'tool_errors':0,'guard_stops':1}
        rows=[{**common,'variant':'control','accepted':True,'tokens':None},
              {**common,'variant':'deduplicate','accepted':False,'tokens':10}]
        result=summarize(rows)
        self.assertIsNone(result['by_variant']['control']['actual_tokens'])
        self.assertIsNone(result['pairs'][0]['token_delta'])
        self.assertEqual(result['lost_success_pairs'],1)
        self.assertEqual(result['new_success_pairs'],0)
        with self.assertRaises(ValueError):
            summarize(rows[:1])
