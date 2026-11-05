"""Publish no-model validator acceptance counts; independent test details stay local."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

from integrations.harness2 import read, sha, write
from integrations.harness2_runtime import ROOT, workspace
from repairflow.telemetry import configuration


def public_rows(output):
    report, protocol = read(output/'report.json'), read(output/'protocol.json')
    if report['status']!='passed' or report['model_calls']!=0:
        raise ValueError('Require completed no-model admission')
    if any(sha(ROOT/name)!=value for name,value in protocol['source_files'].items()):
        raise ValueError('Validator implementation changed')
    return {name:{key:row[key] for key in ('accepted','candidate_static_findings',
                'retained_static_findings','introduced_static_findings','public','reasons')}
            for name,row in report['cases'].items()}


def publish(output):
    from langfuse import Langfuse

    rows = public_rows(output)
    settings = configuration()
    if settings is None:
        raise ValueError('Configure the existing local Langfuse')
    client = Langfuse(**settings,timeout=10,flush_at=1,environment='patch-validator-acceptance')
    trace_id = hashlib.sha256(('patch-validator:'+str(output)).encode()).hexdigest()[:32]
    try:
        root = client.start_observation(name='patch-validator-acceptance',as_type='span',
            trace_context={'trace_id':trace_id},metadata={'experiment_id':output.name,
                'task_id':'toolz-join-unmatched','model_calls':0,'independent_results_published':False,
                'scope':'Four curated mechanism controls; not model repairs'})
        for name,data in rows.items():
            metadata = {'variant':name,'authorship':'saved Agent output' if name=='agent_agg1' else 'control/analyst diagnostic'}
            if name=='agent_agg1':
                agent = read(ROOT/'.tmp/harness2-autonomous-20261104/executions/issue-cc-agg1/toolz-join-unmatched/agg1/agent/report.json')
                metadata['source_inference_trace_id'] = agent['observability']['trace_id']
            root.start_observation(name=name,as_type='span',metadata=metadata,output=data).end()
        root.update(output={'variants':len(rows),'model_calls':0,'acceptance_scope':'public checks and static rules'})
        root.end()
        client.flush()
        with httpx.Client(base_url=settings['base_url'],auth=(settings['public_key'],settings['secret_key']),
                          trust_env=False,timeout=10) as reader:
            for _ in range(20):
                response = reader.get('/api/public/v2/observations',params={'traceId':trace_id,'limit':1000,'fields':'basic,io'})
                response.raise_for_status()
                observations = response.json()['data']
                if len(observations)==len(rows)+1:
                    break
                time.sleep(0.5)
        if len(observations)!=5 or any(row['type']=='GENERATION' for row in observations):
            raise ValueError('Validator trace receipt mismatch')
        if {row['name'] for row in observations if row['name'] in rows}!=set(rows):
            raise ValueError('Missing validation variant in trace')
        for row in observations:
            if row['name'] in rows:
                observed = json.loads(row['output']) if isinstance(row.get('output'),str) else row.get('output')
                if observed!=rows[row['name']]:
                    raise ValueError('Published public validation output mismatch')
        write(output/'langfuse.json',{'status':'passed','trace_id':trace_id,
            'trace_url':client.get_trace_url(trace_id=trace_id),'observations':5,
            'generations':0,'model_calls':0,'published_independent_results':False,
            'publisher_sha256':sha(ROOT/'deploy/langfuse/patch_validation.py')})
    finally:
        client.shutdown()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    publish(workspace(parser.parse_args().output))
