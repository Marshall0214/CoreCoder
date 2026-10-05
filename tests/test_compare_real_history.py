import json
from pathlib import Path

import pytest

from evals.compare_real_history import compare, trace_metrics
from evals.schema import RunConfig


@pytest.fixture
def comparison_setup(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('evals.compare_real_history.admitted_case', lambda *args: (
        {'case_id': 'example'}, {'checks_hash': 'checks', 'revisions': {}}, None, None, {}))
    monkeypatch.setattr('evals.compare_real_history.implementation_metadata', lambda: {
        'source_hash': 'frozen', 'dependencies': {}})

    def worker(*args):
        config, output = args[-2:]
        calls.append(config.search_history)
        root = output / str(len(calls))
        root.mkdir(parents=True)
        (root / 'trace.jsonl').write_text(json.dumps({'event': 'search_completed',
            'reference_hits': int(config.search_history == 'deduplicate'), 'omitted_chars': 12}) + '\n')
        local = {'loaded': {'models': [{'name': config.model, 'digest': 'model'}]}}
        return {'mode': 'live', 'task_id': 'example', 'status': 'budget_exceeded', 'accepted': False,
                'benchmark_eligible': False, 'evaluation_protocol': 'real-agent-loop-development-v1',
                'artifacts': str(root), 'seconds': 1, 'verification': {},
                'implementation': {'source_hash': 'frozen'}, 'worker': {
                    'protocol_prompt_hash': 'prompt', 'tool_schema_hash': 'schema',
                    'ollama_before': local, 'ollama_after': local},
                'metrics': {'budget_accounted_tokens': 100, 'llm_calls': 1, 'missing_usage_calls': 0}}

    monkeypatch.setattr('evals.compare_real_history.run_real', worker)
    return calls, worker


def test_interleaved_comparison_changes_history_only(tmp_path, comparison_setup):
    calls, _ = comparison_setup
    config = RunConfig(mode='live', search_backend='keyword')
    state = compare(Path('admission'), Path('catalog'), 'example', tmp_path / 'batch', config)
    assert state['completed'] and not state['benchmark_eligible']
    assert calls == ['full', 'deduplicate', 'deduplicate', 'full', 'full', 'deduplicate']
    assert state['arms']['full']['runs'] == state['arms']['deduplicate']['runs'] == 3
    freeze = json.loads((tmp_path / 'batch/freeze.json').read_text())
    a, b = freeze['configs'].values()
    assert {key for key in a if a[key] != b[key]} == {'search_history'}
    assert sum(row['trace_metrics']['reference_hits'] for row in state['reports']['deduplicate']) == 3


def test_changed_model_stops_and_preserves_partial_batch(tmp_path, comparison_setup, monkeypatch):
    calls, worker = comparison_setup

    def changed(*args):
        report = worker(*args)
        if len(calls) == 2:
            report['worker']['ollama_after']['loaded']['models'][0]['digest'] = 'different'
        return report

    monkeypatch.setattr('evals.compare_real_history.run_real', changed)
    state = compare(Path('admission'), Path('catalog'), 'example', tmp_path / 'batch',
                    RunConfig(mode='live', search_backend='keyword'))
    assert not state['completed']
    assert 'model changed' in state['stop_reason']
    assert len(calls) == 2
    assert json.loads((tmp_path / 'batch/comparison.json').read_text())['completed'] is False


def test_width_comparison_changes_only_character_budget(tmp_path, comparison_setup, monkeypatch):
    calls, worker = comparison_setup
    widths = []

    def capture(*args):
        widths.append(args[-2].search_max_chars)
        return worker(*args)

    monkeypatch.setattr('evals.compare_real_history.run_real', capture)
    state = compare(Path('admission'), Path('catalog'), 'example', tmp_path / 'batch',
                    RunConfig(mode='live', search_backend='keyword'), axis='search-width')
    assert state['completed']
    assert widths == [6000, 3000, 3000, 6000, 6000, 3000]
    assert calls == ['full'] * 6
    freeze = json.loads((tmp_path / 'batch/freeze.json').read_text())
    a, b = freeze['configs'].values()
    assert {key for key in a if a[key] != b[key]} == {'search_max_chars'}


def test_width_diagnostics_keep_selected_and_discarded_evidence(tmp_path):
    event = {'event': 'search_completed', 'query': 'envvar', 'max_chars': 3000,
             'evidence_chars': 3000, 'response_chars': 3400,
             'selected': [{'path': 'src/click/core.py', 'start_line': 2500, 'truncated': True}],
             'discarded': [{'path': 'src/click/types.py', 'reason': 'evidence_limit'}]}
    (tmp_path / 'trace.jsonl').write_text(json.dumps(event) + '\n')
    result = trace_metrics({'artifacts': str(tmp_path)})
    assert result['evidence_chars'] == 3000 and result['response_chars'] == 3400
    assert result['truncated_chunks'] == 1
    assert result['searches'][0]['discarded'][0]['path'] == 'src/click/types.py'
