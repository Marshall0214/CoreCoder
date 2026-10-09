import hashlib
import json

import pytest

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments import active_iterator_repair_v1 as active
from evals.runner import digest, snapshot
from evals.runtime import Events

CODE = '''_marker = object()
def windowed(seq, n, fillvalue=None, step=1):
    if n <= 0:
        raise ValueError('n must be positive')
    values = list(seq)
    for i in range(0, max(1, len(values)-n+1), step):
        w = values[i:i+n]
        if w:
            yield tuple(w + [fillvalue]*(n-len(w)))
def locate(iterable, pred, window_size=2):
    secret_local = 'must-not-capture-this-local'
    windows = windowed(iterable, window_size, fillvalue=_marker)
    return [i for i, w in enumerate(windows) if pred(*w)]
def replace(iterable, pred, substitutes, window_size=2, count=None):
    for w in windowed(iterable, window_size, fillvalue=_marker):
        yield from substitutes if pred(*w) else w[:1]
def ichunked(iterable, n):
    if n == 0:
        while True:
            yield iter(())
    values = list(iterable)
    for i in range(0, len(values), n):
        yield iter(values[i:i+n])
'''


@pytest.fixture
def case(tmp_path):
    workspace = tmp_path / 'workspace'
    package = workspace / 'more_itertools'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    path = package / 'more.py'
    path.write_text(CODE, encoding='utf-8', newline='')
    job = {'workspace': str(workspace), 'package': 'more_itertools', 'source_root': '.',
           'allowed_files': ['more_itertools/more.py'], 'description': 'Never pass padding to predicates',
           'description_hash': hashlib.sha256(b'Never pass padding to predicates').hexdigest(),
           'original_hash': digest(snapshot(workspace)),
           'evidence': [{'path': 'more_itertools/more.py', 'symbol': '<module>', 'start_line': 1,
                         'end_line': len(CODE.splitlines()), 'content': CODE,
                         'content_hash': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    for name in ('harness', 'frozen_harness'):
        harness = tmp_path / name
        harness.mkdir()
        (harness / 'test_admission.py').write_text('public checks', encoding='utf-8')
        job[name], job[name + '_hash'] = str(harness), digest(snapshot(harness))
    return workspace, job, tmp_path


@pytest.mark.parametrize('arguments', [
    {'cases': []}, {'cases': [{'method': 'exec', 'items': []}]},
    {'cases': [{'method': 'locate', 'items': [True]}]},
    {'cases': [{'method': 'locate', 'items': list(range(9))}]},
    {'cases': [{'method': 'locate', 'items': [1], 'code': 'print(1)'}]},
    {'cases': [{'method': 'locate', 'items': [1], 'window_size': 100}]},
])
def test_diagnostic_bounds_reject_invalid_requests(arguments):
    with pytest.raises(ValueError):
        active.validate_cases(arguments)


def test_model_selected_short_input_observes_windows_and_actual_predicate_args(case):
    workspace, job, root = case
    before = digest(snapshot(workspace))
    result = active.probe(workspace, job, root / 'probe', {'cases': [
        {'method': 'locate', 'items': [4], 'window_size': 2, 'pred': 'sum_equals', 'target': 7},
        {'method': 'locate', 'items': [3, 4], 'window_size': 2, 'target': 7}]})
    assert result['usable']
    short, normal = result['data']['cases']
    assert short['predicate_calls'] == [[4, {'type': 'internal_marker'}]]
    assert short['windows'] == [[4, {'type': 'internal_marker'}]] and short['error_type'] == 'TypeError'
    assert normal['result'] == [0] and normal['iterator_reads'] == [3, 4]
    assert 'must-not-capture-this-local' not in json.dumps(result)
    assert digest(snapshot(workspace)) == before


def test_nonterminating_zero_chunks_are_bounded_and_flagged(case):
    workspace, job, root = case
    result = active.probe(workspace, job, root / 'probe', {'cases': [{'method': 'ichunked', 'items': [1, 2], 'n': 0}]})
    record = result['data']['cases'][0]
    assert not result['usable'] and record['truncated']
    assert len(record['result']) == 12 and record['iterator_reads'] == []


def test_probe_subprocess_does_not_inherit_credentials(case, monkeypatch):
    workspace, job, root = case
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'secret-test-key')
    original = active.run_process
    def run(command, cwd, timeout, stdout, stderr, env):
        assert 'DEEPSEEK_API_KEY' not in env and timeout == 15 and '-I' in command and '-B' in command
        return original(command, cwd, timeout, stdout, stderr, env)
    monkeypatch.setattr(active, 'run_process', run)
    active.probe(workspace, job, root / 'probe', {'cases': [{'method': 'windowed', 'items': [1], 'n': 2}]})


def test_escaped_source_root_is_rejected(case):
    workspace, job, root = case
    with pytest.raises(ValueError, match='escapes'):
        active.probe(workspace, dict(job, source_root='..'), root / 'probe', {'cases': [{'method': 'locate', 'items': []}]})


class Model:
    def __init__(self, first):
        self.first, self.messages = first, []
    def metrics(self):
        return {'llm_calls': len(self.messages), 'budget_accounted_tokens': 100 * len(self.messages)}
    def chat(self, messages, tools):
        self.messages.append(messages)
        if len(self.messages) == 1:
            assert tools == [active.TOOL]
            return self.first
        assert not tools
        return LLMResponse(content=json.dumps({'edits': [{'file': 'more_itertools/more.py',
                           'old': '    return [i for i, w in enumerate(windows) if pred(*w)]', 'new': '    return []'}]}))


def test_two_calls_share_budget_and_tool_result_reaches_patch_generation(case, monkeypatch):
    workspace, job, root = case
    model = Model(LLMResponse(tool_calls=[ToolCall('chosen', 'probe_iterators', {'cases': [
                  {'method': 'locate', 'items': [4], 'window_size': 2}]})]))
    checks = {label: {group: {'passed': False} for group in ('Reproduce', 'Preserve')} for label in ('public', 'frozen')}
    monkeypatch.setattr(active.guarded, 'checked', lambda *args: checks)
    result = active.active(model, job, Events(root / 'trace.jsonl', 'test'))
    assert result['status'] == 'failed_public_validation' and result['original_restored']
    assert result['metrics'] == {'llm_calls': 2, 'budget_accounted_tokens': 200}
    tools = [m for m in model.messages[1] if m['role'] == 'tool']
    assert len(tools) == 1 and 'internal_marker' in tools[0]['content']
    assert digest(snapshot(workspace)) == job['original_hash']


def test_no_diagnostic_request_never_generates_or_publishes_a_patch(case):
    _, job, root = case
    model = Model(LLMResponse(content='No probe'))
    result = active.active(model, job, Events(root / 'trace.jsonl', 'test'))
    assert result['status'] == 'diagnostic_not_requested' and result['original_restored']
    assert result['metrics']['llm_calls'] == 1 and not result['published']


def test_tool_call_count_is_bounded_before_subprocesses(case):
    _, job, root = case
    calls = [ToolCall(str(i), 'probe_iterators', {'cases': [{'method': 'locate', 'items': []}]}) for i in range(3)]
    result = active.active(Model(LLMResponse(tool_calls=calls)), job, Events(root / 'trace.jsonl', 'test'))
    assert result['status'] == 'diagnostic_not_requested' and not list(root.glob('probe-*'))
