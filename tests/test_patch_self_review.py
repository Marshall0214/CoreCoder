import json
from pathlib import Path

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import patch_self_review_v1 as review
from evals.runtime import BudgetExceeded, Events


@pytest.fixture
def job(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    (original / 'code.py').write_text('def f(x):\n    return x + 1\n', encoding='utf-8')
    index = review.baseline.functions.FunctionIndex(original, ['code.py'])
    index.refresh()
    evidence = review.retrieval.retrieve(index, 'f must return x')['evidence']
    return {'workspace': str(original), 'description': 'f must return x',
            'allowed_files': ['code.py'], 'evidence': evidence}


def patch(new):
    return json.dumps({'edits': [{'file': 'code.py', 'old': 'return x + 1', 'new': new}]})


class FakeLLM:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def chat(self, messages, tools=None):
        self.requests.append(messages)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(content=answer, tool_calls=[], prompt_tokens=10, completion_tokens=10)

    def metrics(self):
        return {'llm_calls': len(self.requests), 'budget_accounted_tokens': len(self.requests) * 20}


def generate(job, tmp_path, *answers):
    llm = FakeLLM(*answers)
    events = Events(tmp_path / 'trace.jsonl', 'test-review')
    return review.generate(llm, job, events), llm


def test_review_replaces_against_original_and_preserves_baseline(job, tmp_path):
    result, llm = generate(job, tmp_path, patch('return 0'), patch('return x'))
    assert (tmp_path / 'single/code.py').read_text() == 'def f(x):\n    return 0\n'
    assert (tmp_path / 'self-review/code.py').read_text() == 'def f(x):\n    return x\n'
    assert (Path(job['workspace']) / 'code.py').read_text() == 'def f(x):\n    return x + 1\n'
    assert result['initial']['metrics']['llm_calls'] == 1
    assert result['final']['metrics']['llm_calls'] == 2
    assert len(llm.requests) == 2


def test_grader_fields_are_never_projected(job, tmp_path):
    job.update(checks='PRIVATE_TEST_SENTINEL', after='REFERENCE_SENTINEL', verification='GRADER_SENTINEL')
    _, llm = generate(job, tmp_path, patch('return x'), '{"decision":"keep"}')
    requests = json.dumps(llm.requests)
    assert all(value not in requests for value in ('PRIVATE_TEST_SENTINEL', 'REFERENCE_SENTINEL', 'GRADER_SENTINEL'))


@pytest.mark.parametrize('answer', [
    '{"decision":"keep","extra":1}', 'not JSON', patch('return ('),
    json.dumps({'edits': [{'file': 'code.py', 'old': 'return 0', 'new': 'return x'}]}),
])
def test_invalid_review_cannot_destroy_valid_initial(job, tmp_path, answer):
    result, _ = generate(job, tmp_path, patch('return 0'), answer)
    assert result['review_status'] == 'rejected_invalid_review_kept_initial'
    assert (tmp_path / 'self-review/code.py').read_bytes() == (tmp_path / 'single/code.py').read_bytes()


def test_keep_accepts_only_exact_envelope(job, tmp_path):
    result, _ = generate(job, tmp_path, patch('return x'), '```json\n{"decision":"keep"}\n```')
    assert result['review_status'] == 'kept_initial'


def test_budget_stop_keeps_first_and_does_not_request_third(job, tmp_path):
    result, llm = generate(job, tmp_path, patch('return x'), BudgetExceeded('preflight'))
    assert result['review_stopped'] == 'BudgetExceeded'
    assert len(llm.requests) == 2
    assert result['final']['status'] == 'completed'
    assert (tmp_path / 'self-review/code.py').read_bytes() == (tmp_path / 'single/code.py').read_bytes()


def test_invalid_first_can_be_repaired_without_partial_edits(job, tmp_path):
    result, _ = generate(job, tmp_path, patch('return ('), patch('return x'))
    assert result['initial']['status'] == 'invalid_patch'
    assert (tmp_path / 'single/code.py').read_bytes() == (Path(job['workspace']) / 'code.py').read_bytes()
    assert result['final']['status'] == 'completed'


def test_keep_cannot_make_invalid_first_successful(job, tmp_path):
    result, _ = generate(job, tmp_path, 'not JSON', '{"decision":"keep"}')
    assert result['final']['status'] == 'invalid_patch'


def test_scope_violation_is_rejected(job, tmp_path):
    answer = json.dumps({'edits': [{'file': '../outside.py', 'old': 'return x + 1', 'new': 'return x'}]})
    result = review.apply(answer, Path(job['workspace']), tmp_path / 'candidate', job)
    assert result['status'] == 'invalid_patch'
    assert not (tmp_path / 'outside.py').exists()


def test_failure_categories_do_not_claim_semantic_root_cause():
    row = {'accepted': False, 'worker': {'status': 'completed'},
           'verification': {'groups': {'Target': {'passed': False}, 'Controls': {'passed': True}}}}
    assert review.classify(row) == 'target_failed'
    row['verification']['groups']['Controls']['passed'] = False
    assert review.classify(row) == 'control_regression'
    row['worker']['status'] = 'invalid_patch'
    assert review.classify(row) == 'invalid_patch'
