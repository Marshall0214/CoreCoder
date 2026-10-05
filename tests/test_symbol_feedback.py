import json
import sys

import pytest

from corecoder.llm import LLMResponse
from evals.runner import digest, snapshot
from evals.runtime import Events
from evals.schema import RunConfig
from evals.symbol_feedback import check_public, public_contract, run_symbol_feedback


@pytest.mark.parametrize('initial', ['failure', 'success', 'invalid'])
def test_frozen_public_checks_drive_at_most_one_feedback_call(tmp_path, monkeypatch, initial):
    workspace = tmp_path / 'workspace'
    (workspace / 'src/click').mkdir(parents=True)
    (workspace / 'src/click/__init__.py').write_text('from .core import needle\n')
    (workspace / 'src/click/core.py').write_text('def needle():\n    return False\n')
    code = (b'import unittest, click\nclass PublicContract(unittest.TestCase):\n'
            b'    def test_public(self): self.assertTrue(click.needle())\n')
    monkeypatch.setattr('evals.symbol_feedback.public_contract', lambda description: (code, []))
    fixed = json.dumps({'edits': [{'file': 'src/click/core.py', 'old': 'return False', 'new': 'return True'}]})
    turns = [fixed if initial == 'success' else ('not json' if initial == 'invalid' else '{"edits": []}'), fixed]

    class Model:
        def __init__(self):
            self.calls = []

        def chat(self, messages, tools):
            self.calls.append(messages)
            return LLMResponse(content=turns.pop(0))

    model = Model()
    result = run_symbol_feedback(model, workspace, 'needle', ['src/click/core.py'], RunConfig(mode='live'),
                                 Events(tmp_path / 'trace.jsonl', 'feedback'), sys.executable)
    assert result['public_checks']['original']['assertion_failure']
    assert result['feedback_attempts'] == (1 if initial == 'failure' else 0)
    assert len(model.calls) == (2 if initial == 'failure' else 1)
    if initial == 'failure':
        data = json.loads(model.calls[1][1]['content'])
        assert data['public_check_feedback']['frozen_test_code'].encode() == code
        assert data['public_check_feedback']['source'] == 'public-development-checks-only'
        assert result['public_checks']['final']['passed']
        assert result['initial_evidence_hash'] == result['patch_stages'][0]['evidence_hash']
    if initial == 'invalid':
        assert result['status'] == 'invalid_patch' and 'candidate' not in result['public_checks']
    assert (tmp_path / 'symbol-public-harness/test_admission.py').read_bytes() == code
    assert (tmp_path / 'symbol-public-original/src/click/core.py').read_text().endswith('return False\n')


def test_public_check_contract_requires_matching_public_description():
    with pytest.raises(ValueError, match='supported public'):
        public_contract('Repair an unrelated task.')


def test_public_check_harness_is_frozen_between_stages(tmp_path):
    workspace, harness = tmp_path / 'workspace', tmp_path / 'checks'
    workspace.mkdir()
    harness.mkdir()
    (harness / 'test_admission.py').write_text('original')
    frozen = digest(snapshot(harness))
    (harness / 'test_admission.py').write_text('changed')
    with pytest.raises(ValueError, match='harness changed'):
        check_public(workspace, harness, RunConfig(), Events(tmp_path / 'trace.jsonl', 'freeze'),
                      sys.executable, 'original', frozen)
