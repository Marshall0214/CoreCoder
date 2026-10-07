"""Subprocess fake inference with actual tentative edits and public verification."""
import json
import os
import sys
import time
from pathlib import Path

from corecoder.llm import LLMResponse
from docs.experiments import function_index_audit_v1 as functions
from evals.runtime import BudgetLLM
from evals.schema import RunConfig
from service import tentative

CODE = '''import unittest
from pkg import f
class PublicContract(unittest.TestCase):
    def test_result(self):
        self.assertEqual(f(), 3)
'''


def fixture(root):
    source = root/'fixture-source'
    file = source/'src/pkg/__init__.py'
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('def f():\n    return 1\n', encoding='utf-8')
    canonical = root/'canonical.py'
    canonical.write_text(CODE, encoding='utf-8')
    harness = root/'harness'
    harness.mkdir(exist_ok=True)
    (harness/'test_admission.py').write_bytes(canonical.read_bytes())
    tentative.worker.tentative.canonical_check = lambda task: canonical
    index = functions.FunctionIndex(source, ['src/pkg/__init__.py'])
    index.refresh()
    return source, {'task_id': 'pkg', 'description': 'f must return 3.', 'allowed_files': ['src/pkg/__init__.py'],
                    'evidence': functions.pack(index, index.rank('f'))['evidence'], 'harness': str(harness),
                    'harness_hash': tentative.worker.repair.digest(tentative.worker.repair.snapshot(harness)),
                    'check_code_hash': tentative.hashlib.sha256(canonical.read_bytes()).hexdigest(), 'test_python': sys.executable,
                    'imports': [{'module': 'pkg', 'root': 'src', 'path': 'src/pkg/__init__.py'}], 'policy': 'unified-feedback',
                    'retention_policy': 'edited-first', 'feedback_policy': 'runtime-feedback', 'context_policy': 'source-contract'}


def execute(path):
    root = path.parent
    request = json.loads(path.read_text(encoding='utf-8'))
    source, template = fixture(root)
    calls = 0
    def repair(job, events):
        class Raw:
            model = 'fake'
            def chat(self, messages, tools=None):
                nonlocal calls
                assert (root/'source/src/pkg/__init__.py').read_text() == 'def f():\n    return 1\n'
                calls += 1
                (root/'inference-started').write_text(str(calls), encoding='utf-8')
                time.sleep(float(os.environ.get('CORECODER_TENTATIVE_TEST_DELAY', '0')))
                new = '3' if request['request']['task_id'] == tentative.TASKS[0] else ('2' if calls == 1 else '4')
                old = '1' if calls == 1 else '2'
                return LLMResponse(content=json.dumps({'edits': [{'file': 'src/pkg/__init__.py',
                                                                  'old': f'return {old}', 'new': f'return {new}'}]}),
                                   prompt_tokens=100, completion_tokens=100)
        llm = BudgetLLM(Raw(), RunConfig(token_budget=15000, max_output_tokens=256), events)
        result = tentative.worker.run_candidate(llm, job, events)
        result['metrics'] = llm.metrics()
        return result
    report = tentative.run(path, request.get('approval'), load=lambda task_id: (source, template), execute=repair)
    (root/'result.json').write_text(json.dumps(report), encoding='utf-8')


if __name__ == '__main__':
    execute(Path(sys.argv[1]).resolve())
