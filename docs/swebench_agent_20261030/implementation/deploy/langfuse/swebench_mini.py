"""Publish already graded SWE-bench Mini controls as no-inference dataset experiments."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from deploy.langfuse.verify import payload
from evals.swebench_mini import ROOT, load_entry, sha, summarize, write
from repairflow.telemetry import configuration


def score_values(output):
    if output.get('fresh_model_calls') != 0 or output.get('is_agent_result') is not False:
        raise ValueError('Only no-inference harness controls can be published here')
    return {'official_resolved': output['resolved'],
            'fail_to_pass': output['FAIL_TO_PASS']['passed'] / output['FAIL_TO_PASS']['total'],
            'pass_to_pass': output['PASS_TO_PASS']['passed'] / output['PASS_TO_PASS']['total'],
            'fresh_model_calls': 0}


def publication(entry, controls):
    manifest, row = load_entry(entry)
    report = json.loads((controls / 'report.json').read_text(encoding='utf-8'))
    if (report['status'] != 'passed' or report['fresh_model_calls'] != 0
            or report['entry_manifest_sha256'] != sha(entry / 'manifest.json')):
        raise ValueError('Require successful controls linked to this entry')
    outputs = {}
    for mode in ('unchanged', 'reference'):
        raw = json.loads((controls / mode / 'official-report.json').read_text(encoding='utf-8'))
        parsed = summarize(raw, row)
        output = report[mode]
        if any(output[key] != value for key, value in parsed.items()) or output['mode'] != mode:
            raise ValueError('Summary differs from official grader output')
        if sha(controls / mode / 'patch.diff') != output['patch_sha256']:
            raise ValueError('Local patch changed')
        score_values(output)
        outputs[mode] = output
    # Summary-only dataset input; grading labels, gold patch and logs stay local.
    data = {key: row[key] for key in ('instance_id', 'repo', 'base_commit')}
    data['problem_statement_sha256'] = hashlib.sha256(row['problem_statement'].encode()).hexdigest()
    return manifest, report, data, outputs


def validate_items(rows, experiment, dataset_id, output, expected_scores=None):
    if len(rows) != 1:
        return None
    item = rows[0]
    if (item.get('experimentId') != experiment['experiment_id'] or item.get('traceId') != experiment['trace_id']
            or item.get('experimentDatasetId') != dataset_id or not item.get('endTime')
            or payload(item.get('output')) != output):
        return None
    scores = {row['name']: row['value'] for row in item.get('scores') or []}
    expected = score_values(output) if expected_scores is None else expected_scores
    if any(scores.get(key) != value for key, value in expected.items()):
        return None
    return {'experiment_id': experiment['experiment_id'], 'trace_id': experiment['trace_id'],
            'dataset_id': dataset_id, 'item_count': 1, 'output_matches_local': True,
            'scores': {key: scores[key] for key in expected}}


def publish(entry, controls, output, timeout=120):
    from langfuse import Evaluation, Langfuse
    from langfuse.api import NotFoundError

    manifest, report, data, outputs = publication(entry, controls)
    settings = configuration()
    if settings is None:
        raise ValueError('Enable the explicitly selected local Langfuse configuration')
    client = Langfuse(**settings, timeout=5, flush_at=1, environment='swebench-harness-controls')
    result = {'status': 'incomplete', 'fresh_model_calls': 0, 'is_agent_result': False,
              'source': 'official_grading_replay', 'controls_report_sha256': sha(controls / 'report.json')}
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    try:
        if not client.auth_check():
            raise ValueError('Local Langfuse authentication failed')
        name = 'swebench-mini/admission/' + sha(entry / 'manifest.json')[:12]
        expected = {'official_resolved': True}
        try:
            dataset = client.get_dataset(name)
            if len(dataset.items) != 1 or dataset.items[0].input != data or dataset.items[0].expected_output != expected:
                raise ValueError('Existing dataset differs; do not overwrite it')
        except NotFoundError:
            client.create_dataset(name=name, description='Single-task harness controls; not Agent repair accuracy',
                                  metadata={'source_dataset': manifest['dataset'], 'subset_count': 50,
                                            'admitted_task_count': 1, 'mini_revision': manifest['mini_revision']})
            client.create_dataset_item(dataset_name=name, input=data, expected_output=expected,
                                       metadata={'grading_labels_and_gold_patch': 'local_only'})
            dataset = client.get_dataset(name)
        result.update(dataset_name=name, dataset_id=dataset.id, experiments=[])
        suffix = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:10]
        for mode, saved in outputs.items():
            def task(*, item, _saved=saved, **kwargs):
                if item.input != data:
                    raise ValueError('Unexpected dataset input')
                return _saved

            def evaluator(*, output, **kwargs):
                return [Evaluation(name=key, value=value, data_type='BOOLEAN' if key == 'official_resolved' else 'NUMERIC')
                        for key, value in score_values(output).items()]

            experiment = dataset.run_experiment(
                name='harness-control-' + mode, run_name='harness-control-' + mode + '-' + suffix,
                task=task, evaluators=[evaluator], max_concurrency=1,
                metadata={'source': 'official_grading_replay', 'fresh_inference': False, 'is_agent_result': False,
                          'harness_version': report['harness_version'], 'image_id': report['image_id'],
                          'control_mode': mode, 'report_sha256': result['controls_report_sha256']})
            if len(experiment.item_results) != 1 or experiment.item_results[0].output != saved:
                raise ValueError('SDK experiment task did not return the local control result')
            result['experiments'].append({'mode': mode, 'experiment_id': experiment.experiment_id,
                                          'trace_id': experiment.item_results[0].trace_id,
                                          'url': experiment.experiment_url})
        client.flush()
        result['status'] = 'submitted_unconfirmed'
        write(output, result)
        deadline, receipts = time.monotonic() + timeout, {}
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          timeout=5, trust_env=False) as reader:
            while time.monotonic() < deadline:
                for experiment in result['experiments']:
                    if experiment['mode'] in receipts:
                        continue
                    response = reader.get('/api/public/experiment-items', params={
                        'fromStartTime': since, 'experimentId': experiment['experiment_id'], 'limit': 100,
                        'fields': 'core,dataset,io,scores'})
                    response.raise_for_status()
                    receipt = validate_items(response.json()['data'], experiment, dataset.id, outputs[experiment['mode']])
                    if receipt:
                        receipts[experiment['mode']] = receipt
                if len(receipts) == 2:
                    result.update(status='passed', server_receipt_verified=True, receipts=receipts)
                    return result
                time.sleep(2)
        raise TimeoutError('Experiments and matching scores were not confirmed on the server')
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        write(output, result)
        client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', type=Path, required=True)
    parser.add_argument('--controls', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a new output file within project .tmp')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    result = publish(args.entry.resolve(), args.controls.resolve(), output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
