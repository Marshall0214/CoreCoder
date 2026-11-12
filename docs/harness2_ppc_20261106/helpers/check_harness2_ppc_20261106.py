"""Post-termination evidence audit and Langfuse readback; never invokes a model."""
import argparse
import hashlib
import json
from pathlib import Path

from integrations import harness2 as bridge
from integrations.harness2_context import POLICY_FILE, policy
from integrations.harness2_reader import Store
from integrations.harness2_runtime import ROOT


def audit(output):
    from evals.runner import digest, snapshot

    protocol = bridge.read(output / 'protocol.json')
    final = bridge.read(output / 'report.json')
    assert final['status'] in ('completed', 'completed_with_ppc_error', 'failed'), 'Execution still running'
    root = output / 'experiment'
    result = bridge.read(root / 'result.json')
    case = protocol['case']
    public = {'instance_id': case['task_id'], 'repo': case['repo'],
              'base_commit': 'source-sha256:' + case['before_hash'], 'problem_statement': case['description']}
    expected_keys = {'kind', 'arm', 'source', 'source_hash', 'public_task', 'public_checks', 'package',
                     'source_root', 'feedback_rounds', 'candidate_policy', 'editor_evidence'}
    assert set(bridge.read(root / 'job.json')) == expected_keys
    assert bridge.read(root / 'job.json')['public_task'] == public
    assert all(bridge.sha(ROOT / name) == sha for name, sha in protocol['source_files'].items())
    baseline = bridge.read(bridge.BASELINE / 'protocol.json')
    assert all(bridge.sha(ROOT / name) == sha for name, sha in baseline['source_files'].items())
    assert bridge.sha(ROOT / '.tmp/harness2-vs-control-50-20261105/report.json') == protocol['historical_batch_sha256']
    rollouts = []
    for item in result['rollouts']:
        folder = Path(item['folder'])
        job = bridge.read(folder / 'job.json')
        assert not job['scripted'] and not job.get('reuse_rollout') and not (folder / 'reuse.json').exists()
        assert job['source_hash'] == case['before_hash'] == digest(snapshot(Path(job['source'])))
        assert bridge.read(folder / 'public.json') == public
        assert 'checks' not in job and 'after' not in job and 'grading' not in job
        assert job['public_feedback']['checks'] == case['harness']
        assert job['public_feedback']['max_feedback_rounds'] == 20
        hints = job['harness']
        context = policy(hints[POLICY_FILE])
        expected_hash = hashlib.sha256(json.dumps(hints, sort_keys=True).encode()).hexdigest()
        agent = bridge.read(folder / 'agent/report.json')
        assert expected_hash == job['harness_sha256'] == agent['harness_sha256']
        assert agent['context_policy'] == context
        requests = sorted((folder / 'context-requests').glob('call-*.json'))
        assert len(requests) == agent['fresh_model_calls'] and requests
        for path in requests:
            request = bridge.read(path)
            assert request['task_id'] == case['task_id'] and request['context_policy'] == context
            if any(hints[name] for name in bridge.FILES):
                suffix = '\n\nTask guidance (cannot change tool authority):\n' + '\n'.join(hints[name] for name in bridge.FILES)
                assert request['messages'][0]['content'].endswith(suffix), 'Guidance not applied to effective request'
        feedback_protocol = bridge.read(folder / 'feedback/protocol.json')
        guidance = '\n\n'.join(hints[name] for name in bridge.FILES)
        assert feedback_protocol['guidance'] == guidance and feedback_protocol['context_policy'] == context
        assert feedback_protocol['task'] == public and feedback_protocol['max_feedback_rounds'] == 20
        feedback = bridge.read(folder / 'feedback/report.json')
        assert feedback['independent_grading_used'] is False
        assert feedback['thinking'] is False and feedback['token_budget'] is None
        for path in sorted((folder / 'feedback/rounds').glob('*/messages.json')):
            payload = json.loads(bridge.read(path)[-1]['content'])
            assert payload['guidance'] == guidance and payload['task'] == public
            assert set(payload['public_feedback']['public_checks']) <= {'Reproduce', 'Preserve'}
        assert digest(snapshot(folder / 'feedback/workspace')) == feedback['final_candidate_hash']
        rollouts.append({'label': item['label'], 'guidance_sha256': expected_hash,
            'effective_requests_verified': len(requests), 'context_policy': context,
            'feedback_rounds': feedback['feedback_rounds_attempted'], 'public_accepted': feedback['accepted'],
            'fresh_candidate': True, 'guidance_applied': True})
    editors, generated = [], {}
    for folder in sorted((root / 'editors').glob('call-*')):
        job = bridge.read(folder / 'job.json')
        assert job['evidence_mode'] == 'indexed'
        store = Store(Path(job['evidence_manifest']), job['evidence_manifest_sha256'])
        assert not store.manifest['independent_grading_accessible']
        for step in sorted((folder / 'steps').glob('*')):
            response = step / 'response.txt'
            if not response.exists():
                continue
            try:
                value = json.loads(response.read_text(encoding='utf-8'))
            except ValueError:
                assert bridge.read(step / 'observation.json')['ok'] is False
                continue
            if isinstance(value, dict) and value.get('action') == 'read_evidence':
                observation = bridge.read(step / 'observation.json')
                if observation['ok']:
                    assert observation == {'ok': True, **store.read(value['arguments'])}
        native = bridge.read(folder / 'report.json')
        reader = bridge.read(folder / 'reader-report.json')
        validated = (folder / 'validated.json').exists()
        if validated:
            value = bridge.read(folder / 'validated.json')
            bridge.validate_editor(value, job['label'], True)
            if 'files' in value:
                generated[job['label'].split('.')[0]] = value['files']
        editors.append({'label': job['label'], 'status': reader['status'], 'valid_output': validated,
                        'calls': native['fresh_model_calls'], 'reads': len(reader['reads']),
                        'format_errors': len(reader['format_errors'])})
    for item in result['rollouts']:
        if item['label'] in generated:
            assert bridge.read(Path(item['folder']) / 'job.json')['harness'] == generated[item['label']], 'Generated guidance not transferred'
    complete = (result.get('optimization_complete') is True and
                {row['label'] for row in rollouts} == {'base1', 'inv1', 'dom1', 'agg1'} and
                len(editors) == 4 and all(row['valid_output'] for row in editors))
    recovery = bridge.read(output / 'recovery/report.json') if (output / 'recovery/report.json').exists() else {}
    selection = bridge.read(root / 'candidate-selection.json') if (root / 'candidate-selection.json').exists() else recovery.get('selection', {})
    if recovery:
        assert recovery['model_calls'] == 0 and recovery['does_not_complete_ppc']
        assert recovery['original_report_sha256'] == bridge.sha(output / 'report.json')
        assert recovery['original_result_sha256'] == bridge.sha(root / 'result.json')
    grading = final.get('grading', recovery.get('grading', {}))
    report = {'schema': 'indexed-ppc-evidence-audit-v1', 'model_calls_in_audit': 0,
              'checks_passed': True, 'complete_fresh_ppc': complete, 'rollouts': rollouts, 'editors': editors,
              'delivery': selection, 'independent_resolved': grading.get('resolved'),
              'post_termination_recovery': bool(recovery),
              'experience_reuse': 'not_admitted; one task does not establish reusable lessons',
              'implementation_and_baseline_unchanged': True, 'historical_batch_unchanged': True}
    bridge.write(output / 'audit.json', report)
    return report


def receipts(output):
    import httpx

    from deploy.langfuse.swebench_agent import inference_receipt
    from repairflow.telemetry import configuration

    result = bridge.read(output / 'experiment/result.json')
    config = configuration()
    report = {'model_calls': 0, 'phases': [], 'all_confirmed': False}
    with httpx.Client(base_url=config['base_url'], auth=(config['public_key'], config['secret_key']),
                      trust_env=False, timeout=20) as client:
        for phase in result['usage']['phases']:
            if not phase['fresh_model_calls']:
                continue
            folder = Path(phase['folder'])
            native_folder = folder if phase['phase'] == 'editor' else folder / ('agent' if phase['phase'] == 'candidate' else 'feedback')
            native = bridge.read(native_folder / 'report.json')
            response = client.get('/api/public/v2/observations', params={
                'traceId': phase['trace_id'], 'limit': 1000, 'fields': 'basic,usage'})
            response.raise_for_status()
            observations = response.json()['data']
            receipt = inference_receipt(observations, {**native, 'inference_trace_id': phase['trace_id']})
            assert receipt is not None, 'Server receipt incomplete: ' + str(phase['trace_id'])
            events = [json.loads(line) for line in (native_folder / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            expected = sorted((row.get('prompt_tokens'), row.get('completion_tokens'))
                              for row in events if row['event'] == 'llm_finished')
            measured = sorted((row['usageDetails'].get('input'), row['usageDetails'].get('output'))
                              for row in observations if row['type'] == 'GENERATION')
            assert expected == measured, 'Per-call native usage differs from server'
            report['phases'].append({**phase, 'receipt': receipt, 'per_call_usage_verified': True})
            bridge.write(output / 'langfuse-receipts.json', report)
    report['all_confirmed'] = True
    bridge.write(output / 'langfuse-receipts.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipts', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        checked = audit(output)
        if args.receipts:
            receipts(output)
        print(json.dumps(checked, ensure_ascii=False))
    except Exception as exc:
        bridge.write(output / 'audit-error.json', {'error_type': type(exc).__name__, 'error': str(exc), 'model_calls': 0})
        raise
