import hashlib
import json
from pathlib import Path

import httpx

from deploy.langfuse.swebench_agent import inference_receipt
from repairflow.telemetry import configuration

root = Path('D:/project_other/CoreCoder')
trial = root/'.tmp/harness2-toolz-pilot-20261104-v2'
failed = root/'.tmp/harness2-toolz-pilot-20261104'
settings = configuration()
records = []
paths = []
for directory in (failed, trial):
    paths += list(directory.glob('executions/*/*/*/agent/report.json'))
    paths += list(directory.glob('editors/call-*/report.json'))
with httpx.Client(base_url=settings['base_url'],
        auth=(settings['public_key'],settings['secret_key']),trust_env=False,timeout=15) as client:
    for path in paths:
        report = json.loads(path.read_text(encoding='utf-8'))
        trace_id = report['observability']['trace_id']
        response = client.get('/api/public/v2/observations',params={'traceId':trace_id,'limit':1000,'fields':'basic,usage'})
        response.raise_for_status()
        receipt = inference_receipt(response.json()['data'],{**report,'inference_trace_id':trace_id})
        if receipt is None:
            rows=response.json()['data']
            print(json.dumps({'path':str(path),'rows':len(rows),'names':[(r['name'],r['type']) for r in rows],
                'input':sum((r.get('usageDetails') or {}).get('input',0) for r in rows),
                'output':sum((r.get('usageDetails') or {}).get('output',0) for r in rows),
                'ended':sum(bool(r.get('endTime')) for r in rows)}))
            raise ValueError('Trace usage mismatch: '+str(path))
        records.append({'report':path.relative_to(root).as_posix(),**receipt})
manifest = json.loads((root/'docs/local50-unmetered-20261103.json').read_text(encoding='utf-8'))
packet = root/'docs/local50_unmetered_20261103'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
hashes = manifest['files']
if any(digest(packet/name)!=value for name,value in hashes.items()):
    raise ValueError('Frozen 42-percent evidence changed')
protocol = json.loads((trial/'identity/job.json').read_text(encoding='utf-8'))
baseline = root/'.tmp/local50-unmetered-checkpoint-20261103-v2'
original = json.loads((baseline/'protocol.json').read_text(encoding='utf-8'))
if any(digest(root/name)!=value for name,value in original['source_files'].items()):
    raise ValueError('Baseline source changed')
result = {'status':'passed','receipts':records,'all_attempts_model_calls':sum(r['generation_count'] for r in records),
    'all_attempts_tokens':sum(r['prompt_tokens']+r['completion_tokens'] for r in records),
    'baseline_evidence_files_verified':len(hashes),'baseline_source_unchanged':True,
    'baseline_report_sha256':digest(baseline/'report.json'),'verification_model_calls':0}
(trial/'publication/inference-receipts.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='receipts'}))
