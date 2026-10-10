import pytest

from docs.experiments.targeted_context_v1 import retrieve
from docs.experiments.targeted_repair_v1 import run, trial_config
from evals.symbol_context import apply_symbol_patch


def test_oversized_doc_does_not_hide_target_or_allow_unseen_edits(tmp_path):
    source = 'def remap(value):\n    """' + 'Documentation. ' * 600 + '"""\n    return helper(value)\n\ndef helper(value):\n    return value\n'
    (tmp_path / 'app.py').write_text(source, encoding='utf-8')
    result = retrieve(tmp_path, ['app.py'], 'remap must preserve set values.')
    target = next(r for r in result['evidence'] if r['symbol'] == 'remap')
    assert not target['complete_symbol']
    assert 'return helper(value)' in target['content']
    assert target['content'] in (tmp_path / 'app.py').read_bytes().decode('utf-8')
    assert any(r['symbol'] == 'helper' for r in result['evidence'])
    assert result['metadata']['chars'] <= 6000
    import json
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(json.dumps({'edits': [{'file': 'app.py', 'old': 'Documentation.',
                                                'new': 'Changed.'}]}), tmp_path, ['app.py'], result['evidence'])
    apply_symbol_patch(json.dumps({'edits': [{'file': 'app.py', 'old': 'return helper(value)',
                                            'new': 'return value'}]}), tmp_path, ['app.py'], result['evidence'])
    refreshed = retrieve(tmp_path, ['app.py'], 'remap must preserve set values.')
    assert any('return value' in r['content'] for r in refreshed['evidence'] if r['symbol'] == 'remap')


def test_description_covers_multiple_entry_points_and_excludes_unrelated_method(tmp_path):
    (tmp_path / 'app.py').write_text('def prompt():\n    return 1\ndef confirm():\n    return 2\nclass Other:\n    def insert(self):\n        return 3\n')
    result = retrieve(tmp_path, ['app.py'], 'prompt and confirm must preserve output. Do not insert spaces.')
    required = {r['symbol'] for r in result['metadata']['required_symbols']}
    assert {'prompt', 'confirm'} <= required
    assert 'Other.insert' not in required


def test_protocol_methods_of_named_class_and_no_ambiguous_bare_method(tmp_path):
    (tmp_path / 'app.py').write_text('class Span:\n    def index(self, x):\n        return 0\n    def __contains__(self, x):\n        return False\n    def __len__(self):\n        return 0\nclass Other:\n    def index(self, x):\n        return 1\n')
    result = retrieve(tmp_path, ['app.py'], 'Span must recognize each member, return its index and correct length.')
    required = {r['symbol'] for r in result['metadata']['required_symbols']}
    assert {'Span.index', 'Span.__contains__', 'Span.__len__'} <= required
    assert 'Other.index' not in required


def test_targeted_runner_refuses_full_pool_before_any_execution(tmp_path):
    with pytest.raises(ValueError, match='three targeted failures'):
        run(tmp_path / 'output', 'full')
    assert not (tmp_path / 'output').exists()
    config = trial_config('deepseek-high')
    assert config.token_budget == 60000 and config.max_output_tokens == 32768
    with pytest.raises(ValueError):
        trial_config('deepseek-off')


@pytest.mark.parametrize('correction_passes', [True, False])
@pytest.mark.parametrize('module', ['targeted_feedback_v1', 'public_api_feedback_v1', 'state_type_feedback_v1', 'caller_fallback_feedback_v1', 'public_contract_feedback_v1'])
def test_feedback_retrieves_current_source_and_preserves_rollback(tmp_path, monkeypatch, correction_passes, module):
    import hashlib
    from types import SimpleNamespace
    import importlib
    guard = importlib.import_module('docs.experiments.' + module)
    from evals.runner import digest, snapshot
    from evals.runtime import Events
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    original = 'def prompt():\n    return 1\n'
    (workspace / 'app.py').write_text(original, encoding='utf-8')
    job = {'workspace': str(workspace), 'allowed_files': ['app.py'], 'description': 'prompt must return 3',
           'original_hash': digest(snapshot(workspace)),
           'description_hash': hashlib.sha256(b'prompt must return 3').hexdigest(),
           'evidence': retrieve(workspace, ['app.py'], 'prompt must return 3')['evidence']}
    harnesses = ('harness', 'frozen_harness', 'contract_harness') if module == 'public_contract_feedback_v1' else ('harness', 'frozen_harness')
    for label in harnesses:
        folder = tmp_path / label
        folder.mkdir()
        (folder / 'test_admission.py').write_text('# public checks')
        job[label], job[label + '_hash'] = str(folder), digest(snapshot(folder))
    llm = SimpleNamespace(calls=0)
    llm.metrics = lambda: {'llm_calls': llm.calls}
    def request(llm, workspace, job, evidence, root, stage, feedback=None):
        if stage == 'feedback':
            assert any('return 2' in r['content'] for r in evidence)
            guard.previous.repair.validate_evidence(workspace, job['allowed_files'], evidence)
        llm.calls += 1
        (workspace / 'app.py').write_text('def prompt():\n    return ' + ('2' if stage == 'initial' else '3') + '\n')
        return {'status': 'completed'}
    monkeypatch.setattr(guard.previous, 'request', request)
    monkeypatch.setattr(guard, 'feedback', lambda *args: {'observations': 'public mismatch'})
    def checked(workspace, job, root, stage):
        passed = stage == 'corrected' and correction_passes
        labels = ('public', 'frozen', 'contract') if module == 'public_contract_feedback_v1' else ('public', 'frozen')
        return {label: {'Reproduce': {'passed': passed if label == 'contract' or module != 'public_contract_feedback_v1' else True,
                                    'timed_out': False, 'tests_run': 1}}
                for label in labels}
    monkeypatch.setattr(guard, 'checked', checked)
    result = guard.run_candidate(llm, job, Events(tmp_path / 'trace.jsonl', 'test'))
    assert llm.calls == 2
    assert result['published'] is correction_passes
    assert result['original_restored'] is (not correction_passes)
    if not correction_passes:
        assert (workspace / 'app.py').read_text() == original
