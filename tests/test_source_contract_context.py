import ast
import json
from pathlib import Path

import pytest

from docs.experiments import source_contract_context_v1 as context
from docs.experiments import source_contract_worker_v1 as worker
from docs.experiments import unified_feedback_worker_v1 as original
from evals.runtime import Events

SOURCE = '''class Signer:
    def __init__(self, salt=b"signer"):
        self.salt = salt

class Serializer:
    def __init__(self, salt=b"serializer"):
        self.salt = salt
    def make_signer(self, salt=None):
        if salt is None:
            salt = self.salt
        return Signer(salt=salt)
    def dumps(self, value, salt=None):
        return self.make_signer(salt)
    def loads(self, value, salt=None):
        return self.make_signer(salt)
'''


def job(tmp_path):
    (tmp_path / 'app.py').write_text(SOURCE, encoding='utf-8')
    index = context.unified.context.public.comparison.directed.retrieval.FunctionIndex(tmp_path, ['app.py'])
    index.refresh()
    seed = context.unified.context.public.comparison.directed.retrieval.pack(index, index.rank('salt'))['evidence']
    return {'description': 'Serializer and Signer must accept salt=None.', 'allowed_files': ['app.py'], 'evidence': seed,
            'task_id': original.relations.TASK, 'context_policy': 'source-contract', 'test_python': 'unused', 'imports': []}


def test_facts_preserve_distinct_defaults_and_forwarding_with_provenance(tmp_path):
    data = job(tmp_path)
    sheet, _ = context.facts(tmp_path, data['allowed_files'], data['description'])
    assert "salt=b'signer'" in sheet and "salt=b'serializer'" in sheet
    assert 'call Signer(salt=salt)' in sheet and 'if salt is None' in sheet
    assert 'Serializer.dumps' in sheet and 'Serializer.loads' in sheet
    assert 'sha256=' in sheet and 'inherited/dynamic members unknown' in sheet
    assert 'default_salt' not in sheet and 'effective' not in sheet


def test_packing_is_deterministic_readonly_and_budgeted(tmp_path):
    data = job(tmp_path)
    before = (tmp_path / 'app.py').read_bytes()
    packed = context.pack(tmp_path, data)
    assert packed == context.pack(tmp_path, data)
    assert packed['metadata']['combined_chars'] <= 6000 and len(packed['evidence']) <= 5
    assert (tmp_path / 'app.py').read_bytes() == before
    assert len(context.encoded(packed['source_contract_facts'])) <= 2000


def test_facts_refresh_from_current_candidate_without_historical_default(tmp_path):
    data = job(tmp_path)
    path = tmp_path / 'app.py'
    path.write_text(SOURCE.replace('b"signer"', 'b"new-default"'), encoding='utf-8')
    packed = context.pack(tmp_path, data)
    assert "salt=b'new-default'" in packed['source_contract_facts']
    assert "salt=b'signer'" not in packed['source_contract_facts']
    context.unified.repair.validate_evidence(tmp_path, ['app.py'], packed['evidence'])


def test_unrelated_description_does_not_create_contract_facts(tmp_path):
    job(tmp_path)
    sheet, _ = context.facts(tmp_path, ['app.py'], 'An unrelated failure.')
    assert sheet == ''


@pytest.mark.parametrize('policy,task,changed', [('source-contract', original.relations.TASK, True),
                                              ('baseline', original.relations.TASK, False),
                                              ('source-contract', 'another-task', False)])
def test_editor_receives_exact_displayed_versioned_evidence(tmp_path, monkeypatch, policy, task, changed):
    data = job(tmp_path)
    data.update(context_policy=policy, task_id=task)
    captured = {}
    class LLM:
        def chat(self, messages, tools=None):
            captured['data'] = json.loads(messages[1]['content'])
            return type('Reply', (), {'content': '{"edits": []}', 'tool_calls': []})()
    def transact(text, workspace, allowed, evidence, *args):
        captured['editor'] = evidence
        return {'accepted': True, 'changed_files': [], 'reason': 'committed'}
    monkeypatch.setattr(worker.guard, 'transact', transact)
    events = Events(tmp_path / 'trace.jsonl', policy)
    worker.request_guarded(LLM(), tmp_path, data, data['evidence'], events, 'initial')
    assert ('source_contract_facts' in captured['data']) == changed
    displayed = captured['data']['fragments']
    assert [(r['path'], r['content_hash'], r['content']) for r in displayed] == [
        (r['path'], r['content_hash'], r['content']) for r in captured['editor']]


@pytest.mark.parametrize('name', ['run_candidate', 'pack_feedback', 'transaction_feedback'])
def test_feedback_state_machine_is_identical_to_frozen_workflow(name):
    def definition(module):
        tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), include_attributes=False)
    assert definition(worker) == definition(original)
