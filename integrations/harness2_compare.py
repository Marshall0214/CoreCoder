"""Predeclared local context ablation: one known task, three pairs, no strategy search."""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from integrations.harness2 import BASELINE, FILES, child, read, sha, write
from integrations.harness2_context import DEFAULT, POLICY_FILE, organize
from integrations.harness2_runtime import ROOT, workspace

TASK = 'toolz-join-unmatched'
SCHEDULE = [(1,'control'),(1,'deduplicate'),(2,'deduplicate'),(2,'control'),(3,'control'),(3,'deduplicate')]


def config(variant):
    if variant not in ('control','deduplicate'):
        raise ValueError('Only the two predeclared variants')
    return {**DEFAULT,'deduplicate_reads':variant=='deduplicate'}


def summarize(rows):
    groups = {}
    for variant in ('control','deduplicate'):
        selected = [r for r in rows if r['variant']==variant]
        known = all(r['tokens'] is not None for r in selected)
        groups[variant] = {'runs':len(selected),'accepted':sum(r['accepted'] for r in selected),
            'nonempty_patches':sum(r['nonempty_patch'] for r in selected),
            'target_passed':sum(r['target_passed'] for r in selected),
            'controls_passed':sum(r['controls_passed'] for r in selected),
            'calls':sum(r['calls'] for r in selected),'actual_tokens':sum(r['tokens'] for r in selected) if known else None,
            'agent_seconds':round(sum(r['agent_seconds'] for r in selected),3),
            'tool_executions':sum(r['tool_executions'] for r in selected),
            'tool_errors':sum(r['tool_errors'] for r in selected),
            'guard_stops':sum(r['guard_stops'] for r in selected)}
    pairs = []
    for number in sorted({row['pair'] for row in rows}):
        pair = {row['variant']:row for row in rows if row['pair']==number}
        if set(pair)!=set(groups):
            raise ValueError('Every reported pair needs both variants')
        control, candidate = pair['control'], pair['deduplicate']
        pairs.append({'pair':number,'control_accepted':control['accepted'],'deduplicate_accepted':candidate['accepted'],
            'token_delta':candidate['tokens']-control['tokens'] if None not in (candidate['tokens'],control['tokens']) else None})
    return {'by_variant':groups,'pairs':pairs,
            'new_success_pairs':sum(p['deduplicate_accepted'] and not p['control_accepted'] for p in pairs),
            'lost_success_pairs':sum(p['control_accepted'] and not p['deduplicate_accepted'] for p in pairs)}


def verify_requests(folder, variant):
    before = sorted((folder/'agent').glob('step-*-messages.json'))
    after = sorted((folder/'context-requests').glob('call-*.json'))
    if len(before)!=len(after) or not before:
        raise ValueError('Effective request receipts incomplete')
    changed, deduped = 0, 0
    for original, effective in zip(before,after):
        messages = read(original)
        receipt = read(effective)
        expected = organize(messages,config(variant))
        if receipt['messages']!=expected or receipt['context_policy']!=config(variant):
            raise ValueError('Unexpected guidance or context transformation')
        changed += messages!=expected
        old, new = (json.loads(m[-1]['content']) for m in (messages,expected))
        for key in old.keys()-{'observations','current_fragments'}:
            if old[key]!=new[key]:
                raise ValueError('Task/constraint fields changed')
        if any(fragment not in new['current_fragments'] for fragment in old['current_fragments']):
            raise ValueError('Distinct source evidence was lost')
        deduped += len(old['observations'])-len(new['observations'])
    return {'requests':len(before),'changed_requests':changed,'collapsed_observations':deduped,
            'first_request_sha256':hashlib.sha256(json.dumps(read(after[0])['messages']).encode()).hexdigest()}


def publish(output):
    import httpx
    from langfuse import Langfuse

    from deploy.langfuse.swebench_agent import inference_receipt
    from repairflow.telemetry import configuration

    report = read(output/'report.json')
    settings = configuration()
    if settings is None:
        raise ValueError('Use the existing local Langfuse configuration')
    client = Langfuse(**settings,timeout=10,flush_at=1,environment='harness2-context-comparison')
    trace_id = hashlib.sha256(str(output).encode()).hexdigest()[:32]
    try:
        with httpx.Client(base_url=settings['base_url'],auth=(settings['public_key'],settings['secret_key']),
                          trust_env=False,timeout=15) as reader:
            receipts=[]
            for row in report['runs']:
                agent=read(Path(row['folder'])/'agent/report.json')
                response=reader.get('/api/public/v2/observations',params={
                    'traceId':row['trace_id'],'limit':1000,'fields':'basic,usage'})
                response.raise_for_status()
                receipt=inference_receipt(response.json()['data'],{**agent,'inference_trace_id':row['trace_id']})
                if receipt is None:
                    raise ValueError('Native inference usage not confirmed')
                receipts.append(receipt)
            root=client.start_observation(name='context-deduplication-paired-comparison',as_type='span',
                trace_context={'trace_id':trace_id},metadata={'experiment_id':output.name,'task_id':TASK,
                    'harness_variant':'comparison','strategy_search':False,'independent_grading_after_all_runs':True})
            for row in report['runs']:
                root.start_observation(name=f"pair-{row['pair']}-{row['variant']}",as_type='span',metadata={
                    'experiment_id':output.name,'task_id':TASK,'harness_variant':row['variant'],
                    'pair':row['pair'],'inference_trace_id':row['trace_id']},
                    output={k:row[k] for k in ('accepted','tokens','calls','agent_status')}).end()
                client.create_score(trace_id=row['trace_id'],name='independent_target_controls_passed',
                                    value=int(row['accepted']),data_type='NUMERIC')
            root.update(output=report['summary'])
            root.end()
            client.flush()
            for _ in range(20):
                response=reader.get('/api/public/v2/observations',params={'traceId':trace_id,'limit':1000})
                response.raise_for_status()
                rows=response.json()['data']
                if len(rows)==7:
                    break
                time.sleep(0.5)
            if len(rows)!=7 or any(r['type']=='GENERATION' for r in rows):
                raise ValueError('Comparison trace receipt mismatch')
            write(output/'langfuse.json',{'status':'passed','trace_url':client.get_trace_url(trace_id=trace_id),
                'trace_id':trace_id,'observations':len(rows),'controller_generations':0,'publication_model_calls':0,
                'inference_receipts':receipts})
    finally:
        client.shutdown()


def run(output):
    from evals import local50
    from sandbox import runner

    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    case=next(row for row in read(local50.MANIFEST)['cases'] if row['task_id']==TASK)
    frozen=read(BASELINE/'protocol.json')['source_files']
    code=tuple(frozen)+('integrations/harness2.py','integrations/harness2_context.py','integrations/harness2_compare.py')
    protocol={'name':'context-deduplication-paired-v1','experiment_id':output.name,'task_id':TASK,
        'known_development_task':True,'pairs':3,'schedule':SCHEDULE,'guidance':dict.fromkeys(FILES,''),
        'policies':{name:config(name) for name in ('control','deduplicate')},
        'model':'qwen3.5:27b','thinking':False,'temperature':0,'seed':'not explicitly set',
        'num_ctx':65536,'num_predict':-1,'token_budget':None,'max_steps':20,'max_edits':6,'wall_timeout':1200,
        'repeated_actions':3,'consecutive_errors':3,'candidate_dependency_reads':2,'stop_after_valid_candidate':True,
        'strategy_search':False,'model_retries':0,'independent_grading_after_all_runs':True,
        'source_files':{name:sha(ROOT/name) for name in code},'case':case,
        'baseline_report_sha256':sha(BASELINE/'report.json')}
    write(output/'protocol.json',protocol)
    write(output/'identity/job.json',{'kind':'identity','case':case})
    child(output/'identity/job.json',60)
    runner.ACTIVE_POLICY.set(runner.preflight())
    local50.fixture_controls(case,output/'admission')
    source=output/'input'
    shutil.copytree(case['before'],source,ignore=shutil.ignore_patterns('.git','__pycache__'))
    if local50.digest(local50.snapshot(source))!=case['before_hash']:
        raise ValueError('Original source export changed')
    completed=[]
    for pair,variant in SCHEDULE:
        if any(sha(ROOT/name)!=value for name,value in protocol['source_files'].items()):
            raise ValueError('Frozen implementation changed during the experiment')
        folder=output/'executions'/f'pair-{pair}'/variant
        folder.mkdir(parents=True)
        shutil.copyfile(BASELINE/'tasks'/TASK/'public.json',folder/'public.json')
        hints={**protocol['guidance'],POLICY_FILE:json.dumps(config(variant))}
        write(folder/'job.json',{'kind':'rollout','source':str(source),'source_hash':case['before_hash'],
            'public_sha256':sha(folder/'public.json'),'harness':hints,
            'harness_sha256':hashlib.sha256(json.dumps(hints,sort_keys=True).encode()).hexdigest(),
            'scripted':False,'context_enabled':True,'experiment_id':output.name,'task_id':TASK,'harness_variant':variant})
        # A failed process is preserved, never automatically retried or replaced.
        child(folder/'job.json')
        check=verify_requests(folder,variant)
        completed.append({'pair':pair,'variant':variant,'folder':str(folder),'request_check':check})
        write(output/'progress.json',{'phase':'agent','completed':completed,'grading_available_to_agent':False})
        print(f'pair-{pair} {variant}: execution recorded',flush=True)
    # No grading information is generated until all six Agent executions have stopped.
    rows=[]
    for item in completed:
        folder=Path(item['folder'])
        agent=read(folder/'agent/report.json')
        grade=local50.grade(case,folder)
        actions=read(folder/'agent/actions.json')
        calls=[a for a in actions if a['status'] in ('completed','tool_error')]
        counts=[agent['metrics'][key] for key in ('prompt_tokens','completion_tokens')]
        rows.append({**item,'agent_status':agent['status'],'calls':agent['fresh_model_calls'],
            'tokens':sum(counts) if all(v is not None for v in counts) else None,
            'agent_seconds':agent['seconds'],'trace_id':agent['observability']['trace_id'],
            'nonempty_patch':bool(agent['changed_files']),'patch_sha256':agent['patch_sha256'],
            'target_passed':grade['groups']['Target']['passed'],'controls_passed':grade['groups']['Controls']['passed'],
            'accepted':grade['resolved'],'tool_executions':len(calls),
            'tool_errors':sum(a['status']=='tool_error' for a in calls),'guard_stops':sum(a['status']=='stopped' for a in actions)})
    if len({r['request_check']['first_request_sha256'] for r in rows})!=1:
        raise ValueError('The initial effective requests differ across arms')
    write(output/'identity-final/job.json',{'kind':'identity','case':case})
    child(output/'identity-final/job.json',60)
    report={'status':'completed','protocol_sha256':sha(output/'protocol.json'),'runs':rows,'summary':summarize(rows),
            'seconds_through_grading':round(time.monotonic()-started,3),'baseline_42_percent_unchanged':True,
            'scope':'Three repeats of one known task, not three independent tasks or Harness2 search efficacy'}
    write(output/'report.json',report)
    publish(output)
    print(json.dumps(report['summary']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(workspace(parser.parse_args().output))
