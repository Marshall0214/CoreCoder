import hashlib
import json

import pytest

from docs.experiments import repair_forwarding_worker_v1 as worker
from tests.test_repair_public_feedback import (
    FakeLLM,
    setup,  # noqa: F401 - imported pytest fixture
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.py'
    path.write_text("""class Sender:
    def __init__(self, salt=b'one'):
        self.salt = salt
    def make_signer(self, salt=None):
        if salt is None:
            salt = self.salt
        return self.signer(salt=salt)
    def dumps(self, value, salt=None):
        return self.make_signer(salt=salt).sign(value)
class Receiver:
    def __init__(self, salt=b'two'):
        self.salt = salt
class Unrelated:
    def __init__(self, salt=b'three'):
        self.salt = salt
    def make_signer(self, salt=None):
        salt = self.salt
        return self.signer(salt=salt)
""", encoding='utf-8')
    index = worker.public.comparison.directed.retrieval.FunctionIndex(tmp_path, ['source.py'])
    index.refresh()
    seed = next(c for c in index.chunks if index.names[(c.path, c.start_line, c.end_line)] == 'Sender.dumps')
    return tmp_path, path, [{'path': seed.path, 'symbol': 'Sender.dumps', 'start_line': seed.start_line,
        'end_line': seed.end_line, 'content': seed.content, 'content_hash': seed.content_hash}]


def test_selects_named_constructors_and_state_forwarder_only(source):
    root, _, seeds = source
    packed = worker.forwarding_context(root, ['source.py'], seeds, 'Sender and Receiver must accept salt=None')
    assert [r['symbol'] for r in packed['evidence']] == [
        'Sender.__init__', 'Receiver.__init__', 'Sender.make_signer', 'Sender.dumps']
    assert packed['metadata']['evidence_chars'] <= 6000
    assert packed['metadata']['seed_count'] <= 5
    assert packed['metadata']['selection'][2]['reason'] == 'named_parameter_state_forwarder'


def test_no_named_class_falls_back_to_seeds(source):
    root, _, seeds = source
    packed = worker.forwarding_context(root, ['source.py'], seeds, 'accept salt=None')
    assert [r['symbol'] for r in packed['evidence']] == ['Sender.dumps']


def test_current_source_hash_and_allowlist(source):
    root, path, seeds = source
    path.write_text(path.read_text().replace("b'one'", "b'changed'"), encoding='utf-8')
    packed = worker.forwarding_context(root, ['source.py'], seeds, 'Sender must accept salt=None')
    assert all(r['content_hash'] == hashlib.sha256(path.read_bytes()).hexdigest() for r in packed['evidence'])
    assert "b'changed'" in packed['evidence'][0]['content']
    with pytest.raises(ValueError, match='one to five'):
        worker.forwarding_context(root, [], seeds, 'Sender must accept salt=None')


@pytest.mark.parametrize('policy', ['public-feedback', 'forwarding-feedback'])
def test_shared_initial_prompt_and_bounded_feedback(setup, policy):  # noqa: F811 - pytest fixture injection
    job, events, initial, final, calls = setup
    job['policy'] = policy
    llm = FakeLLM([initial, final])
    result = worker.run_candidate(llm, job, events)
    assert len(llm.messages) == 2 and result['feedback_attempts'] == 1
    assert result['public_checks']['final']['passed']
    first = json.loads(llm.messages[0][1]['content'])
    assert set(first) == {'description', 'allowed_files', 'fragments'}
    assert calls == ['public-original', 'public-candidate', 'public-final']
