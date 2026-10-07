"""Paired synthetic fault recovery; not a real-defect or first-pass benchmark."""

import argparse
import json
import sys
from pathlib import Path

from docs.experiments import thinking_calibration_cases_v1 as fixtures
from docs.experiments import thinking_calibration_v1 as calibration
from docs.experiments import thinking_calibration_worker_v1 as native
from docs.experiments import transaction_feedback_v1 as feedback
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig

ROOT = calibration.ROOT
FAULTS = {
    'unique-falsey': ('return value or fallback', 'return ('),
    'preserve-methods': ("return prefix + ' ' + value", "return prefix + ' ' + value\n    def render(self, prefix, value):\n        return prefix"),
    'annotation-import': ('_t.str_bytes', '_t.DoesNotExist'),
}


def patch(case, edits):
    return json.dumps({'edits': [{'file': 'app.py', 'old': old, 'new': new} for old, new in edits]})


class Scripted:
    model = 'scripted'

    def __init__(self, content):
        self.content = content
    def chat(self, messages, tools=None):
        return native.LLMResponse(content=self.content, prompt_tokens=10, completion_tokens=10)


def run(output, live=False, base='http://127.0.0.1:11434'):
    output = output.resolve()
    if output.is_relative_to(ROOT / 'docs') or output.is_relative_to(ROOT / 'evals'):
        raise ValueError('Output must stay outside experiment code and fixtures')
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), Path(feedback.__file__), Path(feedback.guard.__file__), Path(fixtures.__file__),
             Path(calibration.__file__), Path(native.__file__), ROOT / 'evals/runtime.py',
             ROOT / 'evals/fixed_evidence.py', ROOT / 'evals/symbol_context.py', ROOT / 'evals/process.py',
             ROOT / 'evals/schema.py', ROOT / 'corecoder/llm.py']
    frozen = {p.relative_to(ROOT).as_posix(): calibration.sha(p) for p in paths}
    identity = calibration.identity(base) if live else None
    config = RunConfig(model=calibration.MODEL, base_url=base, token_budget=15000, max_output_tokens=2048, context_tokens=16000)
    report = {'protocol': {'protocol': 'transaction-feedback-probe-v1', 'synthetic': True,
               'fault_injected': True, 'benchmark_eligible': False, 'unique_tasks': 3,
               'live': live, 'max_attempts': 2, 'max_fresh_model_calls_per_branch': 1,
               'seed_model_calls': 0, 'seed_token_charge': 0, 'config': config.to_dict(),
               'thinking': False, 'temperature': 0, 'top_p': 0.95, 'seed': 17,
               'model_identity': identity, 'adapter_hashes': frozen,
               'intervention': 'same rejected seed, unchanged source and guard; feedback differs only by validation diagnostic'},
              'runs': [], 'complete': False, 'model_calls': 0}
    def save():
        report['summary'] = {policy: {'transaction_accepted': sum(r['result']['transaction_accepted'] for r in report['runs'] if r['policy'] == policy),
                              'behavior_passed': sum(r['verification']['passed'] for r in report['runs'] if r['policy'] == policy),
                              'runs': sum(r['policy'] == policy for r in report['runs']),
                              'total_tokens': (sum(r['result']['metrics']['known_prompt_tokens'] + r['result']['metrics']['known_completion_tokens']
                                                   for r in report['runs'] if r['policy'] == policy)
                                               if live and all(not r['result']['metrics']['missing_usage_calls']
                                                               for r in report['runs'] if r['policy'] == policy) else None)}
                             for policy in feedback.POLICIES}
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    for index, case in enumerate(c for c in fixtures.CASES if c['id'] in FAULTS):
        for policy in (feedback.POLICIES if index % 2 == 0 else tuple(reversed(feedback.POLICIES))):
            if any(calibration.sha(ROOT / name) != value for name, value in frozen.items()):
                raise ValueError('Frozen implementation changed')
            root = output / case['id'] / policy
            workspace = root / 'workspace'
            workspace.mkdir(parents=True)
            (workspace / 'app.py').write_bytes(case['source'].encode())
            checks = root / 'checks.py'
            checks.write_bytes(case['checks'].encode())
            check_hash = calibration.sha(checks)
            job = {'workspace': str(workspace), 'description': case['description'], 'allowed_files': ['app.py'],
                   'files': calibration.evidence(workspace), 'test_python': sys.executable, 'policy': policy,
                   'imports': [{'module': 'app', 'root': '.', 'path': 'app.py'}]}
            # The public description and current source enter prompts; checks and reference do not.
            (root / 'job.json').write_text(json.dumps(job, indent=2), encoding='utf-8')
            events = Events(root / 'trace.jsonl', case['id'] + '-' + policy)
            provider = (native.NativeLLM({'model': calibration.MODEL, 'thinking': False, 'base_url': base}, events)
                        if live else Scripted(patch(case, case['reference'])))
            llm = BudgetLLM(provider, config, events)
            result = feedback.run_candidate(llm, job, events, seed_patch=patch(case, [FAULTS[case['id']]]))
            verified = calibration.verify(workspace, checks, root / 'verification', case['source'])
            if calibration.sha(checks) != check_hash:
                raise ValueError('Parent-owned checks changed')
            report['model_calls'] += result['metrics']['llm_calls'] if live else 0
            report['runs'].append({'task_id': case['id'], 'policy': policy, 'checks_sha256': check_hash,
                                  'seed_sha256': feedback.hashlib.sha256(patch(case, [FAULTS[case['id']]]).encode()).hexdigest(),
                                  'result': result, 'verification': verified,
                                  'native': provider.telemetry if live else None})
            save()
            print(f"{case['id']} {policy}: {result['status']}; behavior={verified['passed']}", flush=True)
    if (any(calibration.sha(ROOT / name) != value for name, value in frozen.items())
            or (live and calibration.identity(base) != identity)):
        raise ValueError('Frozen implementation or model identity changed')
    report['complete'] = len(report['runs']) == 6
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    run(args.output, args.live, args.base_url)
