"""Post-hoc local pilot publication; independent grades never enter Agent context."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import httpx

from integrations.harness2 import read, sha, write
from repairflow.telemetry import configuration

PROTOCOL = 'feedback-actions-pilot-five-v1'
SUMMARY = 'feedback-pilot-result'
METRICS = ('llm_calls', 'prompt_tokens', 'completion_tokens', 'known_prompt_tokens',
           'known_completion_tokens', 'missing_usage_calls')


def integer(value):
    return type(value) is int and value >= 0


def metrics(value, calls):
    """Unknown provider usage remains null, with the known lower bound separate."""
    result = {key: value[key] for key in METRICS}
    if (not integer(calls) or result['llm_calls'] != calls
            or any(not integer(result[key]) for key in
                   ('llm_calls', 'known_prompt_tokens', 'known_completion_tokens', 'missing_usage_calls'))
            or result['missing_usage_calls'] > calls):
        raise ValueError('Invalid inference accounting')
    for total, known in (('prompt_tokens', 'known_prompt_tokens'),
                         ('completion_tokens', 'known_completion_tokens')):
        if result[total] is not None and (not integer(result[total]) or result[total] != result[known]):
            raise ValueError('Invalid Token accounting')
    if result['missing_usage_calls'] == 0 and any(result[key] is None for key in
                                               ('prompt_tokens', 'completion_tokens')):
        raise ValueError('Missing Token totals without missing usage')
    if result['missing_usage_calls'] and all(result[key] is not None for key in
                                           ('prompt_tokens', 'completion_tokens')):
        raise ValueError('Incomplete provider usage cannot have complete Token totals')
    if calls == 0 and (result['known_prompt_tokens'] or result['known_completion_tokens']):
        raise ValueError('Token usage without model calls')
    return result


def collect(batch):
    """Read an explicit allowlist; prompts, test bodies and raw errors stay local."""
    batch = Path(batch).resolve()
    protocol, report = read(batch / 'protocol.json'), read(batch / 'report.json')
    digest = sha(batch / 'protocol.json')
    task_ids = protocol['task_ids']
    if (protocol.get('name') != PROTOCOL or report['protocol_sha256'] != digest
            or not task_ids or len(set(task_ids)) != len(task_ids)
            or set(task_ids) != set(report['tasks'])):
        raise ValueError('Pilot protocol or task inventory mismatch')
    outputs = {}
    traces = set()
    for key in task_ids:
        if not isinstance(key, str) or Path(key).name != key or key in {'.', '..'} or ':' in key:
            raise ValueError('Invalid task identifier')
        folder, state = batch / 'tasks' / key, report['tasks'][key]
        task = read(folder / 'public.json')
        if task['instance_id'] != key:
            raise ValueError('Public task identifier mismatch')
        data = {'instance_id': key, 'repo': task['repo'], 'base_commit': task['base_commit'],
                'problem_statement_sha256': hashlib.sha256(task['problem_statement'].encode()).hexdigest(),
                'status': state['status'], 'initial_status': state.get('initial_status'),
                'feedback_status': state.get('feedback_status'), 'public_accepted': state.get('public_accepted'),
                'fresh_model_calls': state['fresh_model_calls'],
                'metrics': metrics(state['metrics'], state['fresh_model_calls']),
                'final_candidate_hash': state.get('final_candidate_hash'), 'phases': []}
        for phase in state['phases']:
            label, trace_id = phase['phase'], phase.get('trace_id')
            calls = phase['fresh_model_calls']
            if (label not in {'initial', 'feedback'} or any(row['phase'] == label for row in data['phases'])
                    or (calls and not trace_id) or (trace_id and trace_id in traces)):
                raise ValueError('Invalid phase/trace mapping')
            if trace_id:
                traces.add(trace_id)
            data['phases'].append({'phase': label, 'trace_id': trace_id, 'fresh_model_calls': calls,
                                   'metrics': metrics(phase['metrics'], calls)})
        if not data['phases'] or any(sum(row['metrics'][field] for row in data['phases']) != data['metrics'][field]
                for field in ('llm_calls', 'known_prompt_tokens', 'known_completion_tokens', 'missing_usage_calls')):
            raise ValueError('Phase accounting differs from task totals')
        if state['status'] == 'graded':
            grade = read(folder / 'grading/report.json')
            feedback = read(folder / 'feedback/report.json')
            if (type(state.get('resolved')) is not bool or type(grade['passed']) is not bool
                    or type(grade['resolved']) is not bool or grade['passed'] != state['resolved']
                    or grade['resolved'] != state['resolved']
                    or feedback['final_candidate_hash'] != state['final_candidate_hash']):
                raise ValueError('Candidate or independent grading mismatch')
            if state['resolved'] and (grade['scope_violations'] or any(
                    (grade.get('groups') or {}).get(name, {}).get('passed') is not True
                    for name in ('Target', 'Controls'))):
                raise ValueError('Successful grade lacks passing independent checks')
            data['resolved'] = state['resolved']
            data['grading_report_sha256'] = sha(folder / 'grading/report.json')
            data['independent_grading'] = {'passed': grade['passed'], 'resolved': grade['resolved'],
                'scope_violation_count': len(grade['scope_violations']), 'groups': {}}
            for group in ('Target', 'Controls'):
                source = (grade.get('groups') or {}).get(group)
                data['independent_grading']['groups'][group] = None if source is None else {
                    name: value for name, value in source.items() if name in
                    {'tests_run', 'passed', 'failures', 'errors', 'skipped', 'timed_out'}
                    and (type(value) is bool or integer(value))}
        outputs[key] = data
    return digest, outputs


def phase_receipt(rows, phase):
    """Confirm actual native usage, including partial or absent provider usage."""
    trace_id = phase['trace_id']
    roots = [row for row in rows if row.get('name') == 'issue-repair']
    calls = [row for row in rows if row.get('type') == 'GENERATION']
    if (len(roots) != 1 or len(calls) != phase['fresh_model_calls']
            or len({row.get('id') for row in rows}) != len(rows)
            or any(row.get('traceId') != trace_id or not row.get('endTime') for row in rows)):
        raise ValueError('Inference count, identity or termination mismatch')
    prompt = completion = missing = 0
    for row in calls:
        usage = row.get('usageDetails') or {}
        if any(name in usage and not integer(usage[name]) for name in ('input', 'output')):
            raise ValueError('Invalid native Token usage')
        prompt += usage.get('input', 0)
        completion += usage.get('output', 0)
        missing += not all(name in usage for name in ('input', 'output'))
    expected = phase['metrics']
    if (prompt != expected['known_prompt_tokens'] or completion != expected['known_completion_tokens']
            or missing != expected['missing_usage_calls']):
        raise ValueError('Server native usage differs from local accounting')
    return {'phase': phase['phase'], 'trace_id': trace_id, 'observation_count': len(rows),
            'generation_count': len(calls), 'all_operations_ended': True,
            'prompt_tokens': expected['prompt_tokens'], 'completion_tokens': expected['completion_tokens'],
            'known_prompt_tokens': prompt, 'known_completion_tokens': completion, 'missing_usage_calls': missing}


def get_rows(reader, trace_id, *, scores=False):
    response = reader.get('/api/public/v3/scores' if scores else '/api/public/v2/observations',
        params={'traceId': trace_id, 'limit': 100 if scores else 1000,
                **({} if scores else {'fields': 'basic,usage,io'})})
    response.raise_for_status()
    result = response.json()
    if result.get('meta', {}).get('totalItems', len(result['data'])) > len(result['data']):
        raise ValueError('Incomplete server page')
    return result['data']


def payload(value):
    return json.loads(value) if isinstance(value, str) else value


def sdk_factory(**kwargs):
    from langfuse import Langfuse

    return Langfuse(**kwargs)


def publish(batch, *, factory=None, reader_factory=None, timeout=60):
    """Return a separate failure receipt on telemetry errors; never rewrite repairs."""
    batch = Path(batch).resolve()
    receipt = {'status': 'failed', 'publication_model_calls': 0, 'content_capture': False,
               'independent_grading_returned_to_agent': False}
    client = None
    try:
        digest, outputs = collect(batch)
        receipt.update(protocol_sha256=digest, task_count=len(outputs))
        settings = configuration()
        if settings is None:
            raise ValueError('Explicit local Langfuse configuration required')
        client = (factory or sdk_factory)(**settings, timeout=10, flush_at=1,
                                         environment='feedback-actions-pilot')
        with (reader_factory or httpx.Client)(base_url=settings['base_url'],
                auth=(settings['public_key'], settings['secret_key']), trust_env=False, timeout=10) as reader:
            inference = []
            for output in outputs.values():
                for phase in output['phases']:
                    if phase['trace_id']:
                        inference.append(phase_receipt(get_rows(reader, phase['trace_id']), phase))
            receipt['inference_receipts'] = inference
            summaries = {}
            for key, output in outputs.items():
                trace_id = hashlib.sha256(('feedback-pilot:' + str(batch) + ':' + key + ':' + digest).encode()).hexdigest()[:32]
                summaries[key] = trace_id
                metadata = {'experiment_id': batch.name, 'task_id': key, 'protocol': PROTOCOL,
                            'protocol_sha256': digest, 'attempt': 1, 'post_termination_publication': True,
                            'independent_grading_returned_to_agent': False, 'publication_model_calls': 0}
                # A confirmed previous import is reusable; never duplicate its observations.
                existing = get_rows(reader, trace_id)
                if existing:
                    roots = [row for row in existing if row.get('name') == SUMMARY]
                    if len(roots) != 1 or payload(roots[0].get('output')) != output:
                        raise ValueError('Existing summary differs from local evidence')
                else:
                    root = client.start_observation(name=SUMMARY, as_type='span',
                        trace_context={'trace_id': trace_id}, metadata=metadata, output=output)
                    if 'independent_grading' in output:
                        root.start_observation(name='independent-grading', as_type='span',
                            metadata={'after_agent_termination': True, 'returned_to_agent': False},
                            output=output['independent_grading']).end()
                    root.end()
                if 'resolved' in output:
                    for target in [trace_id] + [phase['trace_id'] for phase in output['phases'] if phase['trace_id']]:
                        for name, value in (('independent_grading_available', 1),
                                            ('local_target_controls_passed', int(output['resolved']))):
                            client.create_score(trace_id=target, name=name, value=value, data_type='BOOLEAN',
                                score_id=hashlib.sha256((target + ':' + name + ':' + digest).encode()).hexdigest(),
                                metadata=metadata, comment='Independent grading after Agent termination; never Agent feedback')
            client.flush()
            receipt.update(status='submitted_unconfirmed', summary_trace_ids=summaries)
            deadline = time.monotonic() + timeout
            while True:
                confirmed = True
                for key, trace_id in summaries.items():
                    output = outputs[key]
                    rows = get_rows(reader, trace_id)
                    roots = [row for row in rows if row.get('name') == SUMMARY]
                    grades = [row for row in rows if row.get('name') == 'independent-grading']
                    expected = 2 if 'resolved' in output else 1
                    if (len(rows) != expected or len(roots) != 1
                            or any(not row.get('endTime') or row.get('type') == 'GENERATION'
                                   or row.get('traceId') != trace_id for row in rows)
                            or (roots and payload(roots[0].get('output')) != output)
                            or ('resolved' in output and (len(grades) != 1
                                or payload(grades[0].get('output')) != output['independent_grading']))):
                        confirmed = False
                    if 'resolved' in output:
                        for target in [trace_id] + [phase['trace_id'] for phase in output['phases'] if phase['trace_id']]:
                            scores = {row['name']: row['value'] for row in get_rows(reader, target, scores=True)}
                            if (scores.get('independent_grading_available') != 1
                                    or scores.get('local_target_controls_passed') != int(output['resolved'])):
                                confirmed = False
                if confirmed:
                    receipt.update(status='passed', server_receipt_verified=True,
                                   verified_inference_traces=len(inference), verified_task_summaries=len(outputs))
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Pilot publication server receipt mismatch')
                time.sleep(0.5)
    except Exception as exc:  # noqa: BLE001 - optional telemetry cannot discard an Agent result
        receipt.update(status='failed', error_type=type(exc).__name__)
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception as exc:  # noqa: BLE001 - report telemetry cleanup separately
                receipt['shutdown_error_type'] = type(exc).__name__
        write(batch / 'langfuse.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(CORECODER_LANGFUSE_ENABLED='1', CORECODER_LANGFUSE_ENV_FILE=str(args.env_file.resolve()))
    print(json.dumps(publish(args.batch), ensure_ascii=False))


if __name__ == '__main__':
    main()
