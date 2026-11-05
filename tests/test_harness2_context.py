"""Context configuration is bounded data, preserving source and task evidence."""
import copy
import json
import unittest

from integrations.harness2 import FILES, validate_harness
from integrations.harness2_context import DEFAULT, POLICY_FILE, organize, policy


def messages():
    fragment={'path':'pkg/code.py','content_hash':'v1','kind':'file','symbol':None,'offset':0,'content':'code'}
    symbol={**fragment,'kind':'function','symbol':'f','complete_symbol':True,'content':'def f(): return 1'}
    observation={'action':'read_file','arguments':{'path':'pkg/code.py','offset':0},'status':'completed',
                 'result':{'path':'pkg/code.py','content_hash':'v1','offset':0}}
    return [{'role':'system','content':'fixed permissions and output contract'},
            {'role':'user','content':json.dumps({'stage':'candidate','problem_statement':'fix f; preserve g',
              'remaining_steps':4,'remaining_edit_attempts':5,'remaining_dependency_reads':2,
              'current_fragments':[fragment,copy.deepcopy(fragment),symbol],
              'observations':[{**observation,'step':1},{**observation,'step':2},
                              {'action':'read_file','status':'tool_error','error':{'code':'denied'}}]})}]


class ContextTests(unittest.TestCase):
    def test_default_preserves_exact_input_bytes(self):
        source=messages()
        self.assertIs(organize(source,DEFAULT),source)

    def test_reject_unknown_execution_retrieval_and_budget_fields(self):
        for field in ('include_call_sites','max_context_tokens','script','model','permissions','memory'):
            with self.assertRaises(ValueError):
                policy(json.dumps({**DEFAULT,field:True}))
        for value in (1,'yes',None):
            with self.assertRaises(ValueError):
                policy(json.dumps({**DEFAULT,'deduplicate_reads':value}))
        with self.assertRaises(ValueError):
            policy(json.dumps({**DEFAULT,'version':True}))

    def test_duplicate_policy_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            policy(json.dumps(DEFAULT)[:-1]+',"read_index":true}')

    def test_context_file_is_opt_in_and_schema_validated(self):
        values={**dict.fromkeys(FILES,''),POLICY_FILE:json.dumps(DEFAULT)}
        validate_harness(values,True)
        with self.assertRaises(ValueError):
            validate_harness(values)
        with self.assertRaises(ValueError):
            validate_harness({**values,POLICY_FILE:'{"script":"x"}'},True)

    def test_dedup_keeps_latest_read_full_symbol_errors_and_constraints(self):
        source=messages()
        original=copy.deepcopy(source)
        result=organize(source,{**DEFAULT,'deduplicate_reads':True,'complete_symbols_first':True,'read_index':True})
        self.assertEqual(source,original)
        self.assertEqual(result[0],original[0])
        before=json.loads(source[-1]['content'])
        after=json.loads(result[-1]['content'])
        for key in ('problem_statement','remaining_steps','remaining_edit_attempts','remaining_dependency_reads','stage'):
            self.assertEqual(before[key],after[key])
        self.assertEqual(len(after['current_fragments']),2)
        self.assertTrue(after['current_fragments'][0]['complete_symbol'])
        self.assertEqual(after['current_fragments'][0]['content'],'def f(): return 1')
        self.assertEqual(after['observations'][0]['step'],2)
        self.assertEqual(after['observations'][1]['status'],'tool_error')
        self.assertEqual(len(after['visible_read_index']),2)

    def test_same_content_with_different_path_offset_or_version_is_retained(self):
        source=messages()
        payload=json.loads(source[-1]['content'])
        fragment=payload['current_fragments'][0]
        payload['current_fragments']=[fragment,{**fragment,'path':'pkg/other.py'},
              {**fragment,'offset':100},{**fragment,'content_hash':'v2'}]
        source[-1]['content']=json.dumps(payload)
        result=json.loads(organize(source,{**DEFAULT,'deduplicate_reads':True})[-1]['content'])
        self.assertEqual(len(result['current_fragments']),4)

    def test_read_index_is_derived_only_from_current_receipts(self):
        result=json.loads(organize(messages(),{**DEFAULT,'read_index':True})[-1]['content'])
        self.assertEqual([row['path'] for row in result['visible_read_index']],['pkg/code.py']*3)
        self.assertTrue(all('content' not in row for row in result['visible_read_index']))


if __name__=='__main__':
    unittest.main()
