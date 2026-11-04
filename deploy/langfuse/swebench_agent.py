"""Associate one actual local Agent attempt and subsequent official grading with Mini experiments."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from deploy.langfuse.swebench_mini import validate_items
from evals.swebench_agent import public_task
from evals.swebench_mini import ROOT, load_entry, sha, summarize, write
from repairflow.telemetry import configuration


def publication(entry, attempt, grading):
    task, _manifest = public_task(entry)
    agent = json.loads((attempt / 'report.json').read_text(encoding='utf-8'))
    grade = json.loads((grading / 'report.json').read_text(encoding='utf-8'))
    digest = sha(attempt / 'patch.diff')
    if (agent['agent_input_sha256'] != sha(entry / 'agent/input.json')
            or agent['entry_manifest_sha256'] != sha(entry / 'manifest.json')
            or grade['entry_manifest_sha256'] != agent['entry_manifest_sha256']
            or grade['candidate_sha256'] != digest or agent['patch_sha256'] != digest
            or grade['status'] != 'completed' or grade['instance_id'] != task['instance_id']
            or grade['image_id'] != agent['image_id']):
        raise ValueError('Task, image, candidate or grading provenance mismatch')
    if agent['thinking'] is not False or agent['hidden_grading_feedback'] is not False:
        raise ValueError('Unexpected inference/feedback protocol')
    candidate = grade['candidate']
    if candidate['patch_sha256'] != digest or candidate['is_agent_result'] is not True:
        raise ValueError('Not an independently graded Agent candidate')
    _manifest, grading_row = load_entry(entry)
    raw = json.loads((grading / 'candidate/official-report.json').read_text(encoding='utf-8'))
    if any(candidate[key] != value for key, value in summarize(raw, grading_row).items()):
        raise ValueError('Grading summary differs from the official report')
    if (agent['is_agent_result'] is not True or type(agent['fresh_model_calls']) is not int
            or agent['fresh_model_calls'] != agent['metrics']['llm_calls']):
        raise ValueError('Invalid actual Agent call count')
    output = {key: candidate[key] for key in ('resolved', 'FAIL_TO_PASS', 'PASS_TO_PASS')}
    output.update(instance_id=task['instance_id'], model=agent['model'], thinking=False,
                  agent_stop_reason=agent['status'], fresh_model_calls=agent['fresh_model_calls'],
                  is_agent_result=True, metrics=agent['metrics'], patch_sha256=digest,
                  inference_trace_id=agent.get('observability', {}).get('trace_id'),
                  hidden_grading_feedback=False, agent_seconds=agent['seconds'], grading_seconds=candidate['seconds'])
    data = {key: task[key] for key in ('instance_id', 'repo', 'base_commit')}
    data['problem_statement_sha256'] = hashlib.sha256(task['problem_statement'].encode()).hexdigest()
    return data, output


def scores(output):
    values = {'official_resolved': output['resolved'],
              'fail_to_pass': output['FAIL_TO_PASS']['passed'] / output['FAIL_TO_PASS']['total'],
              'fresh_model_calls': output['fresh_model_calls']}
    if output['PASS_TO_PASS']['total']:
        values['pass_to_pass'] = output['PASS_TO_PASS']['passed'] / output['PASS_TO_PASS']['total']
    metrics = output['metrics']
    if metrics.get('prompt_tokens') is not None and metrics.get('completion_tokens') is not None:
        values['actual_total_tokens'] = metrics['prompt_tokens'] + metrics['completion_tokens']
    return values


def inference_receipt(rows, output):
    calls = [row for row in rows if row.get('type') == 'GENERATION']
    roots = [row for row in rows if row.get('name') == 'issue-repair']
    if (len(roots) != 1 or len(calls) != output['fresh_model_calls']
            or any(not row.get('endTime') or row.get('traceId') != output['inference_trace_id'] for row in rows)):
        return None
    metrics = output['metrics']
    measured = [row.get('usageDetails') or {} for row in calls]
    if metrics.get('usage_status') == 'known' and (
            sum(row.get('input', 0) for row in measured) != metrics['prompt_tokens']
            or sum(row.get('output', 0) for row in measured) != metrics['completion_tokens']):
        return None
    return {'trace_id': output['inference_trace_id'], 'generation_count': len(calls),
            'usage_status': metrics.get('usage_status'), 'prompt_tokens': metrics.get('prompt_tokens'),
            'completion_tokens': metrics.get('completion_tokens'), 'all_operations_ended': True}


def publish(entry, attempt, grading, output, timeout=120):
    from langfuse import Evaluation, Langfuse

    data, saved = publication(entry, attempt, grading)
    settings = configuration()
    client = Langfuse(**settings, timeout=5, flush_at=1, environment='swebench-agent-results')
    result = {'status': 'incomplete', 'source': 'local_agent_result_import',
              'original_fresh_model_calls': saved['fresh_model_calls'], 'publication_model_calls': 0}
    try:
        name = 'swebench-mini/admission/' + sha(entry / 'manifest.json')[:12]
        dataset = client.get_dataset(name)
        if len(dataset.items) != 1 or dataset.items[0].input != data:
            raise ValueError('Require the same frozen control dataset')

        def task(*, item, **kwargs):
            if item.input != data:
                raise ValueError('Unexpected dataset item')
            return saved

        def evaluator(*, output, **kwargs):
            return [Evaluation(name=key, value=value, data_type='BOOLEAN' if key == 'official_resolved' else 'NUMERIC')
                    for key, value in scores(output).items()]

        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        suffix = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:10]
        experiment = dataset.run_experiment(name='local-repository-agent-v1', run_name='local-agent-v1-' + suffix,
            task=task, evaluators=[evaluator], max_concurrency=1,
            metadata={'source': 'local_agent_result_import', 'is_agent_result': True,
                      'inference_trace_id': saved['inference_trace_id'], 'fresh_inference_in_import': False,
                      'agent_report_sha256': sha(attempt / 'report.json'), 'grading_report_sha256': sha(grading / 'report.json')})
        record = {'experiment_id': experiment.experiment_id, 'trace_id': experiment.item_results[0].trace_id}
        result.update(dataset_id=dataset.id, experiment=record, url=experiment.experiment_url,
                      inference_trace_id=saved['inference_trace_id'], scores=scores(saved))
        client.create_score(trace_id=saved['inference_trace_id'], name='official_resolved',
                            value=int(saved['resolved']), data_type='BOOLEAN',
                            comment='Official grading after Agent termination; never fed back to the Agent')
        client.flush()
        result['status'] = 'submitted_unconfirmed'
        deadline = time.monotonic() + timeout
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          timeout=5, trust_env=False) as reader:
            while time.monotonic() < deadline:
                response = reader.get('/api/public/experiment-items', params={
                    'fromStartTime': since, 'experimentId': experiment.experiment_id, 'limit': 100,
                    'fields': 'core,dataset,io,scores'})
                response.raise_for_status()
                receipt = validate_items(response.json()['data'], record, dataset.id, saved, scores(saved))
                response = reader.get('/api/public/v2/observations', params={
                    'traceId': saved['inference_trace_id'], 'limit': 1000, 'fields': 'basic,usage'})
                response.raise_for_status()
                actual = inference_receipt(response.json()['data'], saved)
                response = reader.get('/api/public/v3/scores', params={'traceId': saved['inference_trace_id'], 'limit': 100})
                response.raise_for_status()
                original_scores = {row['name']: row['value'] for row in response.json()['data']}
                if receipt and actual and original_scores.get('official_resolved') == saved['resolved']:
                    actual['official_resolved'] = original_scores['official_resolved']
                    result.update(status='passed', server_receipt_verified=True,
                                  experiment_receipt=receipt, inference_receipt=actual)
                    return result
                time.sleep(2)
        raise TimeoutError('Experiment scores or original inference usage did not match local artifacts')
    finally:
        write(output, result)
        client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', type=Path, required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--grading', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a new output file within project .tmp')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    print(json.dumps(publish(args.entry.resolve(), args.attempt.resolve(), args.grading.resolve(), output)))


if __name__ == '__main__':
    main()
