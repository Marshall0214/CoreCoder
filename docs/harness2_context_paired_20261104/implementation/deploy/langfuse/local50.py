"""Import local50 results and check original inference usage, without new model calls."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from deploy.langfuse.swebench_agent import inference_receipt
from deploy.langfuse.verify import payload
from evals.swebench_mini import ROOT, sha, write
from repairflow.telemetry import configuration


def scores(output):
    result = {'grading_available': int('resolved' in output)}
    if 'resolved' in output:
        result['local_target_controls_passed'] = int(output['resolved'])
        result['fresh_model_calls'] = output['fresh_model_calls']
        if output['total_tokens'] is not None:
            result['actual_total_tokens'] = output['total_tokens']
    return result


def collect(batch):
    report = json.loads((batch / 'report.json').read_text(encoding='utf-8'))
    protocol = json.loads((batch / 'protocol.json').read_text(encoding='utf-8'))
    if report['protocol_sha256'] != sha(batch / 'protocol.json'):
        raise ValueError('Batch protocol changed')
    inputs, outputs = {}, {}
    for key in protocol['task_ids']:
        folder = batch / 'tasks' / key
        task = json.loads((folder / 'public.json').read_text(encoding='utf-8')) if (folder / 'public.json').exists() else None
        if task is None:
            inputs[key] = {'instance_id': key}
        else:
            inputs[key] = {name: task[name] for name in ('instance_id', 'repo', 'base_commit')}
            inputs[key]['problem_statement_sha256'] = hashlib.sha256(task['problem_statement'].encode()).hexdigest()
        state = report['tasks'][key]
        output = {'instance_id': key, 'status': state['status'], 'grading_scope': 'local hand-authored Target + Controls'}
        if state['status'] == 'graded':
            agent = json.loads((folder / 'agent/report.json').read_text(encoding='utf-8'))
            grade = json.loads((folder / 'grading/report.json').read_text(encoding='utf-8'))
            if (sha(folder / 'agent/patch.diff') != agent['patch_sha256'] or grade['resolved'] != state['resolved']
                    or state['resolved'] != grade['passed']):
                raise ValueError('Candidate or independent grade mismatch')
            output.update({name: state[name] for name in ('resolved', 'fresh_model_calls', 'total_tokens', 'agent_status')})
            output.update(metrics=agent['metrics'], inference_trace_id=state.get('trace_id'),
                          Target=(grade.get('groups') or {}).get('Target'),
                          Controls=(grade.get('groups') or {}).get('Controls'),
                          scope_violations=grade['scope_violations'],
                          candidate_execution_failure=grade.get('candidate_execution_failure'))
        outputs[key] = output
    if len(inputs) != 50:
        raise ValueError('Require all 50 scheduled tasks')
    return inputs, outputs


def verify(rows, dataset_id, experiment_id, outputs):
    seen = set()
    for row in rows:
        output = payload(row.get('output'))
        key = output.get('instance_id') if isinstance(output, dict) else None
        if (key not in outputs or key in seen or output != outputs[key] or not row.get('endTime')
                or row.get('experimentDatasetId') != dataset_id or row.get('experimentId') != experiment_id):
            return False
        observed = {score['name']: score['value'] for score in row.get('scores') or []}
        if any(observed.get(name) != value for name, value in scores(output).items()):
            return False
        seen.add(key)
    return seen == set(outputs)


def publish(batch):
    from langfuse import Evaluation, Langfuse
    from langfuse.api import NotFoundError

    inputs, outputs = collect(batch)
    settings = configuration()
    if settings is None:
        raise ValueError('Local Langfuse must be explicitly configured')
    client = Langfuse(**settings, timeout=10, flush_at=1, environment='local50-chain-validation')
    receipt = {'status': 'incomplete', 'publication_model_calls': 0, 'historical_94_percent_reproduction': False}
    try:
        name = 'local50/chain/' + sha(batch / 'protocol.json')[:12]
        try:
            dataset = client.get_dataset(name)
        except NotFoundError:
            client.create_dataset(name=name, description='Current repository Agent on 50 known small fixtures; not SWE-bench',
                                  metadata={'protocol_sha256': sha(batch / 'protocol.json'), 'thinking': False})
            dataset = client.get_dataset(name)
        existing = {item.input['instance_id']: item.input for item in dataset.items}
        if set(existing) - set(inputs) or any(inputs[key] != value for key, value in existing.items()):
            raise ValueError('Existing dataset differs')
        for key, value in inputs.items():
            if key not in existing:
                client.create_dataset_item(dataset_name=name, input=value)
        dataset = client.get_dataset(name)

        def task(*, item, **kwargs):
            key = item.input['instance_id']
            if item.input != inputs[key]:
                raise ValueError('Dataset input changed')
            return outputs[key]

        def evaluator(*, output, **kwargs):
            return [Evaluation(name=key, value=value, data_type='NUMERIC') for key, value in scores(output).items()]

        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        experiment = dataset.run_experiment(name='current-agent-local50-chain', run_name=batch.name,
            task=task, evaluators=[evaluator], max_concurrency=1,
            metadata={'result_import_only': True, 'inference_in_import': False, 'historical_94_percent_reproduction': False})
        for output in outputs.values():
            if output.get('inference_trace_id') and 'resolved' in output:
                client.create_score(trace_id=output['inference_trace_id'], name='local_target_controls_passed',
                                    value=int(output['resolved']), data_type='NUMERIC')
        client.flush()
        receipt.update(status='submitted_unconfirmed', dataset_id=dataset.id, dataset_name=name,
                       experiment_id=experiment.experiment_id, url=experiment.experiment_url)
        deadline = time.monotonic() + 120
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          trust_env=False, timeout=10) as reader:
            while time.monotonic() < deadline:
                response = reader.get('/api/public/experiment-items', params={
                    'fromStartTime': since, 'experimentId': experiment.experiment_id, 'limit': 100,
                    'fields': 'core,dataset,io,scores'})
                response.raise_for_status()
                if verify(response.json()['data'], dataset.id, experiment.experiment_id, outputs):
                    break
                time.sleep(2)
            else:
                raise TimeoutError('Experiment scores not confirmed')
            receipt['inference_receipts'] = []
            for output in outputs.values():
                if not output.get('inference_trace_id'):
                    continue
                response = reader.get('/api/public/v2/observations', params={
                    'traceId': output['inference_trace_id'], 'limit': 1000, 'fields': 'basic,usage'})
                response.raise_for_status()
                value = inference_receipt(response.json()['data'], output)
                if value is None:
                    raise ValueError('Original model calls/usage mismatch: ' + output['instance_id'])
                receipt['inference_receipts'].append(value)
        receipt.update(status='passed', server_receipt_verified=True, verified_dataset_items=50,
                       verified_inference_traces=len(receipt['inference_receipts']))
        return receipt
    finally:
        write(batch / 'langfuse.json', receipt)
        client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    if not batch.is_relative_to(ROOT / '.tmp'):
        parser.error('Use project .tmp')
    os.environ.update(CORECODER_LANGFUSE_ENABLED='1',
                      CORECODER_LANGFUSE_ENV_FILE=str(ROOT / '.tmp/langfuse-local/.env'))
    print(json.dumps(publish(batch)))


if __name__ == '__main__':
    main()
