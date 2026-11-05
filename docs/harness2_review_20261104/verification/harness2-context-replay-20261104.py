import hashlib
import json
from pathlib import Path

from evals.context_policy import request_breakdown
from integrations.harness2_context import DEFAULT, organize

root=Path('D:/project_other/CoreCoder')
trial=root/'.tmp/harness2-toolz-pilot-20261104-v2'
output=root/'.tmp/harness2-review-20261104/context-replay.json'
active={key:1 if key=='version' else True for key in DEFAULT}
records=[]
for label in ('base1','inv1','dom1','agg1'):
    folder=trial/'executions/issue-cc-agg1/toolz-join-unmatched'/label/'agent'
    before_estimate=after_estimate=0
    for path in sorted(folder.glob('step-*-messages.json')):
        messages=json.loads(path.read_text(encoding='utf-8'))
        assert organize(messages,DEFAULT) is messages
        transformed=organize(messages,active)
        source=json.loads(messages[-1]['content'])
        target=json.loads(transformed[-1]['content'])
        for key in source.keys()-{'observations','current_fragments'}:
            assert source[key]==target[key]
        for row in source['current_fragments']:
            assert row in target['current_fragments']
        for row in source['observations']:
            if row.get('status')!='completed' or row.get('action') not in ('read_file','read_symbol'):
                assert row in target['observations']
        before_estimate+=request_breakdown(messages,[])['request_estimate']
        after_estimate+=request_breakdown(transformed,[])['request_estimate']
    records.append({'variant':label,'requests':len(list(folder.glob('step-*-messages.json'))),
        'before_request_estimate_sum':before_estimate,'after_request_estimate_sum':after_estimate})
smoke=root/'.tmp/harness2-context-smoke-20261104'
saved=list(smoke.glob('executions/*/*/*/context-requests/*.json'))
assert len(saved)==8
for path in saved:
    receipt=json.loads(path.read_text(encoding='utf-8'))
    payload=json.loads(receipt['messages'][-1]['content'])
    assert all(receipt[k] for k in ('experiment_id','task_id','harness_variant'))
    if receipt['harness_variant']=='base1':
        assert receipt['context_policy']==DEFAULT
        assert 'visible_read_index' not in payload
    else:
        assert 'visible_read_index' in payload
old_packet=root/'docs/harness2_20261104'
manifest=json.loads((root/'docs/harness2-20261104.json').read_text(encoding='utf-8'))
assert all(hashlib.sha256((old_packet/name).read_bytes()).hexdigest()==value for name,value in manifest['files'].items())
baseline=root/'.tmp/local50-unmetered-checkpoint-20261103-v2'
protocol=json.loads((baseline/'protocol.json').read_text(encoding='utf-8'))
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in protocol['source_files'].items())
result={'scope':'Offline pre-guidance request replay, not new inference or observed token savings',
        'new_model_calls':0,'policy':active,'default_exact_identity':True,
        'preserved_all_distinct_fragments_and_failures':True,'records':records,
        'smoke_effective_requests_verified':len(saved),'old_packet_files_verified':len(manifest['files']),
        'baseline_source_unchanged':True}
output.write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
