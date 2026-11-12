"""Offline protocol, candidate-integrity and accounting checks for the five-case pilot."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from evals import feedback_pilot_v2 as pilot
from evals.runner import changes, digest, snapshot
from evals.swebench_agent import PUBLIC_FIELDS

PRIVATE_MARKER = 'INDEPENDENT-ANSWER-DO-NOT-PROMPT-91a6b'
REFERENCE_MARKER = 'REFERENCE-BODY-DO-NOT-PROMPT-74e2c'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def frozen_case(root, task_id):
    case = {'task_id': task_id, 'repo': 'example/pkg', 'package': 'pkg', 'source_root': '.',
            'description': 'total must double its argument.', 'allowed_files': ['pkg/calc.py'],
            'answer_chunk': REFERENCE_MARKER}
    for label in ('before', 'after', 'harness', 'checks'):
        folder = root / task_id / label
        folder.mkdir(parents=True)
        if label in {'before', 'after'}:
            (folder / 'pkg').mkdir()
            expression = 'value * 2' if label == 'after' else 'value + 2'
            (folder / 'pkg/calc.py').write_text('def total(value):\n    return ' + expression + '\n', encoding='utf-8')
            (folder / 'pkg/helper.py').write_text('FACTOR = 2\n', encoding='utf-8')
            (folder / '.keep').write_text('hidden metadata\n', encoding='utf-8')
            (folder / 'payload.bin').write_bytes(b'\x00\xff\xfe\x80')
            if label == 'after':
                (folder / 'reference-only.txt').write_text(REFERENCE_MARKER, encoding='utf-8')
        else:
            text = PRIVATE_MARKER if label == 'checks' else 'Public Reproduce and Preserve checks only'
            (folder / 'test_admission.py').write_text(text, encoding='utf-8')
        case[label] = str(folder)
        case[label + '_hash'] = digest(snapshot(folder))
    return case


@pytest.fixture
def selected(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(pilot.ROOT / '.tmp'), 'Run with a project D: basetemp'
    ids = tuple(f'fixture-{number}' for number in range(5))
    cases = [frozen_case(tmp_path, name) for name in ids]
    cases[1]['source_root'] = 'src'
    manifest = tmp_path / 'manifest.json'
    write_json(manifest, {'cases': [frozen_case(tmp_path, 'not-selected'), *reversed(cases)]})
    monkeypatch.setattr(pilot, 'TASK_IDS', ids)
    monkeypatch.setattr(pilot, 'CODE', ('repairflow/feedback_observability.py',))
    return cases, manifest


def test_prepare_freezes_exactly_selected_five_without_answer_bodies(tmp_path, selected):
    cases, manifest = selected
    output = tmp_path / 'prepared'
    protocol = pilot.prepare(output, manifest)
    assert protocol['task_ids'] == [case['task_id'] for case in cases]
    assert len(protocol['cases']) == 5 and protocol['name'] == pilot.PROTOCOL
    assert protocol['thinking'] is False and protocol['strategy_search'] is False
    assert protocol['token_budget'] is protocol['max_output_tokens'] is None
    assert protocol['initial_max_requests'] == protocol['feedback_max_requests'] == 20
    assert protocol['initial_seconds'] == protocol['feedback_seconds'] == 1200
    assert protocol['model_call_seconds'] == 480 and protocol['cases'][1]['source_root'] == 'src'
    assert protocol['manifest_sha256'] == pilot.sha(manifest)
    assert PRIVATE_MARKER not in json.dumps(protocol) and REFERENCE_MARKER not in json.dumps(protocol)
    assert all('answer_chunk' not in row for row in protocol['cases'])
    for name, expected in protocol['source_files'].items():
        assert pilot.sha(output / 'implementation' / name) == expected
    assert pilot.read(output / 'report.json')['protocol_sha256'] == pilot.sha(output / 'protocol.json')
    assert not (output / 'tasks').exists(), 'Preparing does not execute or copy reference answers'


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'source-tamper', 'public-tamper', 'private-tamper'])
def test_prepare_rejects_ambiguous_or_modified_frozen_cases(tmp_path, selected, change):
    cases, manifest = selected
    data = pilot.read(manifest)
    if change == 'duplicate':
        data['cases'].append(copy.deepcopy(cases[0]))
    elif change == 'missing':
        data['cases'] = [row for row in data['cases'] if row['task_id'] != cases[0]['task_id']]
    else:
        key = {'source-tamper': 'before', 'public-tamper': 'harness', 'private-tamper': 'checks'}[change]
        (Path(cases[0][key]) / 'unexpected.txt').write_text('tampered', encoding='utf-8')
    write_json(manifest, data)
    with pytest.raises(ValueError):
        pilot.prepare(tmp_path / 'rejected', manifest)
    assert not (tmp_path / 'rejected').exists()


def initial_candidate(folder, case, edits=None):
    shutil.copytree(case['before'], folder / 'baseline')
    baseline = snapshot(folder / 'baseline')
    inventory = {name: value for name, value in baseline.items() if name.endswith('.py')}
    agent = folder / 'initial/agent'
    workspace = agent / 'workspace'
    workspace.mkdir(parents=True)
    for name, content in inventory.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name, content in (edits or {'pkg/calc.py': b'def total(value):\n    return value * 2\n'}).items():
        (workspace / name).write_bytes(content)
    changed, patch = changes(inventory, snapshot(workspace))
    (agent / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
    write_json(agent / 'baseline-files.json', {name: hashlib.sha256(value).hexdigest() for name, value in inventory.items()})
    write_json(agent / 'report.json', {'changed_files': changed, 'patch_sha256': pilot.sha(agent / 'patch.diff')})
    return agent, baseline


def test_candidate_merge_restores_hidden_and_nontext_files(tmp_path):
    case = frozen_case(tmp_path, 'merge')
    folder = tmp_path / 'task'
    agent, baseline = initial_candidate(folder, case)
    initial_export = snapshot(agent / 'workspace')
    assert '.keep' not in initial_export and 'payload.bin' not in initial_export
    candidate = pilot.candidate_input(folder, case)
    current = snapshot(candidate)
    assert current['.keep'] == baseline['.keep'] and current['payload.bin'] == baseline['payload.bin']
    assert current['pkg/calc.py'] == initial_export['pkg/calc.py']
    assert snapshot(folder / 'baseline') == baseline
    assert not (candidate / 'reference-only.txt').exists()
    assert changes(baseline, current)[0] == ['pkg/calc.py']


@pytest.mark.parametrize('change', ['patch', 'workspace', 'inventory', 'baseline', 'unauthorized', 'delete'])
def test_candidate_merge_rejects_tampering_and_unauthorized_changes(tmp_path, change):
    case = frozen_case(tmp_path, 'rejected-merge')
    folder = tmp_path / 'task'
    edits = {'pkg/helper.py': b'FACTOR = 999\n'} if change == 'unauthorized' else None
    agent, _ = initial_candidate(folder, case, edits)
    if change == 'patch':
        (agent / 'patch.diff').write_text('tampered patch', encoding='utf-8')
    elif change == 'workspace':
        (agent / 'workspace/pkg/calc.py').write_text('def total(value):\n    return 99\n', encoding='utf-8')
    elif change == 'inventory':
        inventory = pilot.read(agent / 'baseline-files.json')
        inventory['pkg/calc.py'] = '0' * 64
        write_json(agent / 'baseline-files.json', inventory)
    elif change == 'baseline':
        (folder / 'baseline/pkg/calc.py').write_text('modified baseline', encoding='utf-8')
    elif change == 'delete':
        (agent / 'workspace/pkg/calc.py').unlink()
        changed, patch = changes({name: value for name, value in snapshot(folder / 'baseline').items()
                                  if name.endswith('.py')}, snapshot(agent / 'workspace'))
        (agent / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
        write_json(agent / 'report.json', {'changed_files': changed, 'patch_sha256': pilot.sha(agent / 'patch.diff')})
    with pytest.raises(ValueError):
        pilot.candidate_input(folder, case)
    assert not (folder / 'candidate-input').exists()


def phase(name, calls, prompt, completion, missing):
    return {'phase': name, 'fresh_model_calls': calls, 'metrics': {'known_prompt_tokens': prompt,
            'known_completion_tokens': completion, 'missing_usage_calls': missing}}


def test_aggregate_usage_counts_partial_calls_and_both_phases():
    phases = [phase('initial', 2, 100, 20, 0), phase('feedback', 3, 200, 7, 1)]
    result = pilot.aggregate_usage(phases)
    assert result['llm_calls'] == 5 and result['missing_usage_calls'] == 1
    assert result['known_prompt_tokens'] == 300 and result['known_completion_tokens'] == 27
    assert result['known_tokens_minimum'] == 327
    assert result['prompt_tokens'] is result['completion_tokens'] is None
    assert result['usage_status'] == 'partial' and result['token_budget'] is None


def test_aggregate_usage_distinguishes_empty_and_measured_known_results():
    empty = pilot.aggregate_usage([])
    assert empty['llm_calls'] == 0 and empty['usage_status'] == 'not_applicable'
    known = pilot.aggregate_usage([phase('initial', 1, 100, 8, 0), phase('feedback', 1, 0, 0, 0)])
    assert known['prompt_tokens'] == 100 and known['completion_tokens'] == 8
    assert known['known_tokens_minimum'] == 108 and known['usage_status'] == 'known'


def test_summarize_keeps_usage_from_failed_tasks_and_incomplete_phases(monkeypatch):
    monkeypatch.setattr(pilot, 'TASK_IDS', ('one', 'two', 'three', 'four', 'five'))
    tasks = {'one': {'status': 'graded', 'resolved': True, 'public_accepted': True,
                     'phases': [phase('initial', 2, 100, 20, 0), phase('feedback', 3, 200, 7, 1)]},
             'two': {'status': 'graded', 'resolved': False, 'public_accepted': False,
                     'phases': [phase('initial', 1, 4, 2, 0)]},
             'three': {'status': 'infra_error', 'phases': [phase('initial', 2, 50, 3, 1)]}}
    result = pilot.summarize(tasks)
    assert result['scheduled'] == 5 and result['graded'] == 2 and result['resolved'] == 1
    assert result['public_accepted'] == 1 and result['infra_errors'] == 1
    assert result['fresh_model_calls'] == result['metrics']['llm_calls'] == 8
    assert result['metrics']['known_tokens_minimum'] == 386
    assert result['metrics']['missing_usage_calls'] == 2


def test_feedback_worker_passes_only_public_task_and_keeps_private_artifacts_outside(tmp_path, monkeypatch):
    from evals import swebench_agent
    from repairflow import feedback_repair_v2, issue_providers

    case = frozen_case(tmp_path, 'worker')
    folder = tmp_path / 'worker-job'
    folder.mkdir()
    candidate_input = folder / 'candidate-input'
    shutil.copytree(case['before'], candidate_input)
    task = {'instance_id': case['task_id'], 'repo': case['repo'], 'base_commit': 'public-source-hash',
            'problem_statement': case['description']}
    write_json(folder / 'public.json', task)
    job = {'baseline': case['before'], 'candidate': str(candidate_input), 'public_checks': case['harness'],
           'baseline_hash': case['before_hash'], 'candidate_hash': case['before_hash'],
           'public_checks_hash': case['harness_hash'], 'allowed_files': case['allowed_files'],
           'readable_files': ['pkg/calc.py', 'pkg/helper.py'], 'source_root': 'src', 'package': 'pkg',
           'public_task': str(folder / 'public.json'), 'public_task_sha256': pilot.sha(folder / 'public.json'),
           'experiment_id': 'pilot-test', 'task_id': case['task_id'], 'protocol': pilot.PROTOCOL,
           'phase': 'feedback', 'attempt': 1}
    write_json(folder / 'job.json', job)
    captured = {}

    class Observer:
        root = None

        def __init__(self, *args, **kwargs):
            captured['telemetry_task'] = args[1]

        def event(self, *args, **kwargs):
            pass

        def finish(self, result):
            return {'status': 'disabled'}

    def no_model_calls(*args, **kwargs):
        pytest.fail('Offline feedback plumbing must not perform inference')

    def run(baseline, candidate, allowed, public_checks, package, public_task, output, **kwargs):
        assert set(public_task) == PUBLIC_FIELDS and public_task == task
        assert baseline == Path(case['before']) and public_checks == Path(case['harness'])
        assert candidate == candidate_input and candidate != baseline
        assert package == 'pkg' and allowed == case['allowed_files']
        assert kwargs['source_root'] == 'src' and kwargs['context_contract'] is True
        assert kwargs['max_feedback_rounds'] == 20 and kwargs['timeout'] == 1200
        assert kwargs['readable_files'] == ['pkg/calc.py', 'pkg/helper.py']
        assert all(name not in kwargs for name in ('checks', 'grader', 'after', 'reference'))
        assert PRIVATE_MARKER not in json.dumps(public_task) and REFERENCE_MARKER not in json.dumps(public_task)
        output.mkdir()
        captured['ran'] = True
        return {'status': 'agent_finished_unresolved', 'accepted': False, 'changed_files': []}

    monkeypatch.setattr(swebench_agent, 'AgentTelemetry', Observer)
    monkeypatch.setattr(issue_providers.OllamaProvider, 'chat', no_model_calls)
    monkeypatch.setattr(feedback_repair_v2, 'run', run)
    pilot.feedback_worker(folder / 'job.json')
    report = pilot.read(folder / 'feedback/report.json')
    assert captured['ran'] and report['fresh_model_calls'] == 0
    assert report['metrics']['token_budget'] is None and report['execution_mode'] == 'ollama'
    assert report['observability']['status'] == 'disabled'


def test_feedback_worker_refuses_changed_public_input_before_observer_or_model(tmp_path, monkeypatch):
    from evals import swebench_agent

    case = frozen_case(tmp_path, 'worker-tamper')
    folder = tmp_path / 'worker-tamper-job'
    folder.mkdir()
    task = {'instance_id': case['task_id'], 'repo': case['repo'], 'base_commit': 'public-source-hash',
            'problem_statement': case['description']}
    write_json(folder / 'public.json', task)
    job = {'public_task': str(folder / 'public.json'), 'public_task_sha256': '0' * 64}
    write_json(folder / 'job.json', job)

    def no_observation(*args, **kwargs):
        pytest.fail('Changed public task must be rejected before constructing inference/telemetry')

    monkeypatch.setattr(swebench_agent, 'AgentTelemetry', no_observation)
    with pytest.raises(ValueError, match='Public task changed'):
        pilot.feedback_worker(folder / 'job.json')


def test_trace_recovery_keeps_failed_and_pending_usage_in_the_denominator(tmp_path):
    path = tmp_path / 'interrupted.jsonl'
    rows = [
        {'event': 'llm_started', 'call_id': 'llm-1'},
        {'event': 'llm_finished', 'call_id': 'llm-1', 'prompt_tokens': 10, 'completion_tokens': 2},
        {'event': 'llm_started', 'call_id': 'llm-2'},
        {'event': 'llm_failed', 'call_id': 'llm-2', 'prompt_tokens': 7, 'completion_tokens': None},
        {'event': 'llm_started', 'call_id': 'llm-3'},
    ]
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n{"incomplete":', encoding='utf-8')
    phase = pilot.trace_usage(path, 'feedback')
    metrics = pilot.aggregate_usage([phase])
    assert metrics['llm_calls'] == 3 and metrics['missing_usage_calls'] == 2
    assert metrics['known_tokens_minimum'] == 19
    assert metrics['prompt_tokens'] is metrics['completion_tokens'] is None


@pytest.mark.parametrize(('line', 'status', 'count'), [
    ('released slot: truncated = 0\n', 'not_verified', 0),
    ('WARN msg="truncating input prompt" limit=65536 prompt=80000\n', 'warning_observed', 1),
])
def test_log_evidence_only_flags_explicit_positive_input_truncation(tmp_path, line, status, count):
    source = tmp_path / 'server.log'
    source.write_text(line, encoding='utf-8')
    report = pilot.log_evidence({'path': str(source), 'size': 0}, tmp_path / 'evidence.json')
    assert report['server_input_truncation'] == status
    assert len(report['truncation_warnings']) == count
    assert report['input_completeness_verified'] is False


def test_proven_zero_call_phase_can_have_empty_metrics_without_fabricating_usage():
    phase = pilot.phase_usage({'fresh_model_calls': 0, 'metrics': {}}, 'initial')
    assert phase['metrics']['llm_calls'] == 0 and phase['metrics']['known_tokens_minimum'] == 0
    assert phase['metrics']['usage_status'] == 'not_applicable'
