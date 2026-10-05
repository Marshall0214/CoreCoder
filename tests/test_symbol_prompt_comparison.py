import json

import pytest

from evals.compare_symbol_prompts import compare
from evals.schema import RunConfig


@pytest.mark.parametrize('mismatch', [False, True])
@pytest.mark.parametrize('axis', ['symbol-prompt', 'public-feedback'])
def test_comparison_freezes_schedule_and_rejects_changed_evidence(tmp_path, monkeypatch, mismatch, axis):
    inputs = ({'case_id': 'fake'}, {'checks_hash': 'checks', 'revisions': {}},
              tmp_path / 'checks', tmp_path / 'source', {})
    monkeypatch.setattr('evals.compare_symbol_prompts.admitted_case', lambda *args: inputs)
    metadata = {'source_hash': 'implementation', 'dependencies': {}}
    monkeypatch.setattr('evals.compare_symbol_prompts.implementation_metadata', lambda: metadata)
    monkeypatch.setattr('evals.compare_symbol_prompts.write_summary', lambda *args: None)
    calls = []

    def run(*args, workflow, symbol_prompt_policy):
        calls.append('public-feedback' if workflow == 'symbol-feedback' else symbol_prompt_policy)
        phase = {'loaded': {'models': []},
                 'identity': {'models': [{'name': 'local-model', 'digest': 'fixed-model'}]}}
        return {'implementation': metadata, 'worker': {
            'evidence_hash': 'changed' if mismatch and len(calls) == 2 else 'same',
            'protocol_prompt_hash': symbol_prompt_policy, 'tool_schema_hash': 'none',
            'ollama_before': phase, 'ollama_after': phase},
            'metrics': {'budget_accounted_tokens': 10, 'llm_calls': 1},
            'seconds': 1, 'status': 'failed_verification', 'accepted': False}

    monkeypatch.setattr('evals.compare_symbol_prompts.run_real', run)
    output = tmp_path / 'comparison'
    state = compare(tmp_path / 'admission', tmp_path / 'catalog', 'fake', output,
                     RunConfig(mode='live', model='local-model'), repeat=3, axis=axis)
    freeze = json.loads((output / 'freeze.json').read_text())
    variant = 'behavior-check' if axis == 'symbol-prompt' else 'public-feedback'
    assert [row['arm'] for row in freeze['schedule']] == [
        'baseline', variant, variant, 'baseline', 'baseline', variant]
    assert state['completed'] is not mismatch
    if mismatch:
        assert len(calls) == 2 and 'Evidence' in state['stop_reason']
        assert sum(len(rows) for rows in state['reports'].values()) == 2
    else:
        assert len(calls) == 6 and state['arms']['baseline']['accepted'] == 0
        assert state['model_digest'] == 'fixed-model'


def test_ollama_identity_is_available_for_an_unloaded_model(monkeypatch):
    import io

    from evals.worker import ollama_metadata

    def open_request(request, timeout):
        if request.full_url.endswith('/api/tags'):
            result = {'models': [{'name': 'local-model', 'digest': 'manifest'},
                                 {'name': 'other-model', 'digest': 'irrelevant'}]}
        elif request.full_url.endswith('/api/ps'):
            result = {'models': []}
        else:
            result = {}
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr('evals.worker.urlopen', open_request)
    metadata = ollama_metadata(RunConfig(model='local-model', base_url='http://localhost:11434/v1'))
    assert metadata['loaded']['models'] == []
    assert metadata['identity']['models'] == [{'name': 'local-model', 'digest': 'manifest'}]
