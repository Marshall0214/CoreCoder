"""Import a complete scheduled Mini-50 batch; no inference and no duplicate token generations."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from deploy.langfuse.swebench_agent import publication, scores
from deploy.langfuse.verify import payload
from evals.swebench_mini import ROOT, sha, write
from repairflow.telemetry import configuration


def collect(batch):
    protocol = json.loads((batch / 'protocol.json').read_text(encoding='utf-8'))
    report = json.loads((batch / 'report.json').read_text(encoding='utf-8'))
    if report['protocol_sha256'] != sha(batch / 'protocol.json'):
        raise ValueError('Batch protocol changed')
    inputs, outputs = {}, {}
    for key in protocol['instance_ids']:
        state = report['tasks'].get(key, {})
        if state.get('status') == 'graded':
            folder = batch / 'tasks' / key
            data, result = publication(batch / 'entries' / key, folder / 'agent', folder / 'grading')
            if state['resolved'] != result['resolved']:
                raise ValueError('Batch summary differs from independent grade')
        else:
            task = json.loads((batch / 'entries' / key / 'agent/input.json').read_text(encoding='utf-8'))
            data = {name: task[name] for name in ('instance_id', 'repo', 'base_commit')}
            data['problem_statement_sha256'] = hashlib.sha256(task['problem_statement'].encode()).hexdigest()
            result = {'instance_id': key, 'status': state.get('status', 'not_run'), 'official_grading_available': False}
        inputs[key], outputs[key] = data, result
    if len(inputs) != 50:
        raise ValueError('Require all 50 scheduled dataset items, including infrastructure failures')
    return protocol, inputs, outputs


def publish(batch):
    from langfuse import Evaluation, Langfuse
    from langfuse.api import NotFoundError

    protocol, inputs, outputs = collect(batch)
    settings = configuration()
    if settings is None:
        raise ValueError('Enable local Langfuse explicitly')
    client = Langfuse(**settings, timeout=10, flush_at=1, environment='swebench-mini-batch')
    receipt = {'status': 'incomplete', 'publication_model_calls': 0, 'scheduled_items': 50,
               'source': 'completed_batch_result_import', 'protocol_sha256': sha(batch / 'protocol.json')}
    try:
        name = 'swebench-mini/batch/' + receipt['protocol_sha256'][:12]
        try:
            dataset = client.get_dataset(name)
        except NotFoundError:
            client.create_dataset(name=name, description='Fixed community Mini-50; local model without thinking',
                                  metadata={'source_dataset': 'MariusHobbhahn/swe-bench-verified-mini',
                                            'mini_revision': protocol['mini_revision'], 'protocol_sha256': receipt['protocol_sha256']})
            dataset = client.get_dataset(name)
        existing = {item.input['instance_id']: item for item in dataset.items}
        if set(existing) - set(inputs) or any(item.input != inputs[key] for key, item in existing.items()):
            raise ValueError('Existing batch dataset differs')
        for key, data in inputs.items():
            if key not in existing:
                client.create_dataset_item(dataset_name=name, input=data,
                                           metadata={'reference_patch_and_test_labels': 'local_only'})
        dataset = client.get_dataset(name)
        if len(dataset.items) != 50:
            raise ValueError('Batch dataset item count mismatch')

        def task(*, item, **kwargs):
            key = item.input['instance_id']
            if item.input != inputs[key]:
                raise ValueError('Dataset input changed')
            return outputs[key]

        def evaluator(*, output, **kwargs):
            values = scores(output) if 'resolved' in output else {}
            values['grading_available'] = int('resolved' in output)
            return [Evaluation(name=key, value=value,
                               data_type='BOOLEAN' if key in {'official_resolved', 'grading_available'} else 'NUMERIC')
                    for key, value in values.items()]

        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        experiment = dataset.run_experiment(name='local-repository-agent-v1-mini50',
            run_name='mini50-' + batch.name, task=task, evaluators=[evaluator], max_concurrency=1,
            metadata={'source': 'completed_batch_result_import', 'fresh_inference_in_import': False,
                      'protocol_sha256': receipt['protocol_sha256'], 'model': protocol['model'], 'thinking': False})
        for result in outputs.values():
            if result.get('inference_trace_id') and 'resolved' in result:
                client.create_score(trace_id=result['inference_trace_id'], name='official_resolved',
                                    value=int(result['resolved']), data_type='BOOLEAN',
                                    comment='Independent grading after Agent stopped; never feedback to Agent')
        client.flush()
        receipt.update(status='submitted_unconfirmed', dataset_id=dataset.id, dataset_name=name,
                       experiment_id=experiment.experiment_id, url=experiment.experiment_url)
        deadline = time.monotonic() + 150
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          trust_env=False, timeout=10) as reader:
            while time.monotonic() < deadline:
                response = reader.get('/api/public/experiment-items', params={
                    'fromStartTime': since, 'experimentId': experiment.experiment_id, 'limit': 100,
                    'fields': 'core,dataset,io,scores'})
                response.raise_for_status()
                rows = response.json()['data']
                if verify(rows, dataset.id, experiment.experiment_id, outputs):
                    receipt.update(status='passed', server_receipt_verified=True, verified_items=50)
                    return receipt
                time.sleep(2)
        raise TimeoutError('Batch experiment ingestion not confirmed')
    finally:
        write(batch / 'langfuse.json', receipt)
        client.shutdown()


def verify(rows, dataset_id, experiment_id, outputs):
    seen = set()
    for row in rows:
        output = payload(row.get('output'))
        key = output.get('instance_id') if isinstance(output, dict) else None
        if (key not in outputs or key in seen or output != outputs[key] or not row.get('endTime')
                or row.get('experimentDatasetId') != dataset_id or row.get('experimentId') != experiment_id):
            return False
        values = {item['name']: item['value'] for item in row.get('scores') or []}
        expected = scores(output) if 'resolved' in output else {}
        expected['grading_available'] = int('resolved' in output)
        if any(values.get(name) != value for name, value in expected.items()):
            return False
        seen.add(key)
    return seen == set(outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    if not batch.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a project .tmp batch')
    os.environ.update(CORECODER_LANGFUSE_ENABLED='1',
                      CORECODER_LANGFUSE_ENV_FILE=str(ROOT / '.tmp/langfuse-local/.env'))
    print(json.dumps(publish(batch)))


if __name__ == '__main__':
    main()
