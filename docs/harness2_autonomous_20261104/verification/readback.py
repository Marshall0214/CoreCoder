import json
from pathlib import Path

import httpx

from deploy.langfuse.swebench_agent import inference_receipt
from integrations.harness2 import read, sha, write
from integrations.harness2_runtime import ROOT
from repairflow.telemetry import configuration

trial=ROOT/'.tmp/harness2-autonomous-20261104'
report=read(trial/'report.json')
protocol=read(trial/'protocol.json')
prereg=read(ROOT/'.tmp/harness2-autonomous-prereg-20261104.json')
assert report['status']=='completed' and not report['scripted']
assert protocol['context_enabled'] and protocol['task']==prereg['task_id']
assert all(value==protocol['source_files'][name] for name,value in prereg['implementation'].items())
recovery=read(trial/'recovery-protocol.json')
assert recovery['original_protocol_sha256']==sha(trial/'protocol.json')
assert recovery['implementation_sha256']==sha(trial/'recovery-implementation/harness2.py')
assert recovery['evidence_implementation_sha256']==sha(ROOT/'integrations/harness2_evidence.py')
assert all(sha(ROOT/name)==value for name,value in protocol['source_files'].items() if name!='integrations/harness2.py')
settings=configuration()
receipts=[]
with httpx.Client(base_url=settings['base_url'],auth=(settings['public_key'],settings['secret_key']),
                  timeout=15,trust_env=False) as client:
    for row in report['executions']:
        path=(next(Path(r['folder'])/'agent/report.json' for r in report['rollouts'] if r['label']==row['label'])
              if row['phase']=='rollout' else trial/'editors'/row['label']/'report.json')
        actual=read(path)
        response=client.get('/api/public/v2/observations',params={
            'traceId':row['inference_trace_id'],'limit':1000,'fields':'basic,usage'})
        response.raise_for_status()
        receipt=inference_receipt(response.json()['data'],{**actual,'inference_trace_id':row['inference_trace_id']})
        assert receipt is not None, str(path)
        receipts.append({'label':row['label'],'phase':row['phase'],**receipt})
assert sum(r['generation_count'] for r in receipts)==report['fresh_model_calls']
assert sum(r['prompt_tokens']+r['completion_tokens'] for r in receipts)==report['actual_tokens']
requests=[]
for rollout in report['rollouts']:
    folder=Path(rollout['folder'])
    job=read(folder/'job.json')
    effective=sorted((folder/'context-requests').glob('*.json'))
    actual=read(folder/'agent/report.json')
    assert len(effective)==actual['fresh_model_calls']
    for path in effective:
        request=read(path)
        assert request['experiment_id']==trial.name and request['task_id']==prereg['task_id']
        assert request['harness_variant']==rollout['label'] and request['context_policy']==actual['context_policy']
    requests.append({'label':rollout['label'],'effective_requests':len(effective),'policy':actual['context_policy'],
                      'harness_sha256':job['harness_sha256']})
old={}
for manifest,folder in (('harness2-20261104.json','harness2_20261104'),
                         ('harness2-review-20261104.json','harness2_review_20261104'),
                         ('harness2-context-paired-20261104.json','harness2_context_paired_20261104'),
                         ('local50-unmetered-20261103.json','local50_unmetered_20261103')):
    data=read(ROOT/'docs'/manifest)
    assert all(sha(ROOT/'docs'/folder/name)==value for name,value in data['files'].items())
    old[manifest]={'sha256':sha(ROOT/'docs'/manifest),'verified_files':len(data['files'])}
baseline=ROOT/'.tmp/local50-unmetered-checkpoint-20261103-v2'
assert all(sha(ROOT/name)==value for name,value in read(baseline/'protocol.json')['source_files'].items())
write(trial/'publication/inference-receipts.json',{'status':'passed','verification_model_calls':0,
    'model_calls':report['fresh_model_calls'],'actual_tokens':report['actual_tokens'],
    'inference_receipts':receipts,'request_receipts':requests,'previous_packets':old,'baseline_source_unchanged':True})
print(json.dumps({'status':'passed','calls':report['fresh_model_calls'],'tokens':report['actual_tokens'],
                  'traces':len(receipts),'effective_requests':sum(r['effective_requests'] for r in requests),
                  'adopted_passed':report['adopted_passed']}))
