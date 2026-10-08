"""One development task, shared recorded first candidate and two fresh corrections."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

from corecoder.llm import LLMResponse
from docs.experiments import predicate_runtime_feedback_v1 as runtime
from docs.experiments import system_comparison_v1 as baseline
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = runtime.previous
TASK = 'more-predicate-sentinel'
POLICIES = ('unchanged-feedback', 'predicate-runtime')


def shared_feedback(outcomes, workspace, job, root):
    source = Path(job['shared_first'])
    if digest(snapshot(workspace)) != job['shared_candidate_hash']:
        raise ValueError('Shared candidate changed before correction')
    old = baseline.load(source / 'worker-result.json')['initial_checks']
    for suite in ('public', 'frozen'):
        for group in ('Reproduce', 'Preserve'):
            for key in ('passed', 'tests_run', 'failures', 'errors'):
                if outcomes[suite][group].get(key) != old[suite][group].get(key):
                    raise ValueError('Public execution differs from shared observations')
    messages = baseline.load(source / 'feedback-messages.json')
    feedback = json.loads(messages[1]['content'])['public_check_feedback']
    if feedback['test_code'] != (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'):
        raise ValueError('Shared public test code changed')
    return feedback


class SharedFirstProvider:
    """Charge historical first-call usage to both task budgets; generate only round two."""
    def __init__(self, provider, source):
        self.provider, self.source = provider, source
        self.calls, self.model = provider.calls, provider.model

    def chat(self, messages, tools=None):
        if not self.calls:
            expected = baseline.load(self.source / 'initial-messages.json')
            if messages != expected or tools:
                raise ValueError('First request differs from recorded candidate')
            old = baseline.load(self.source / 'worker-result.json')['provider_calls'][0]
            call = dict(old, replayed=True, seconds=0, historical_source=str(self.source))
            self.calls.append(call)
            return LLMResponse(content=(self.source / 'initial-response.txt').read_text(encoding='utf-8'),
                               tool_calls=[], prompt_tokens=old['prompt_tokens'], completion_tokens=old['completion_tokens'])
        response = self.provider.chat(messages, tools)
        self.calls[-1]['replayed'] = False
        return response


def worker(path):
    job = baseline.load(path)
    root = path.parent
    events = Events(root / 'trace.jsonl', job['policy'])
    provider = llm = None
    result = {'status': 'agent_error', 'published': False}
    try:
        previous.repair.check_identity(previous.repair.config())
        provider = previous.Provider('qwen', events)
        shared = SharedFirstProvider(provider, Path(job['shared_first']))
        llm = previous.CheckedBudgetLLM(shared, previous.repair.config(), events)
        run = runtime.run_candidate if job['policy'] == 'predicate-runtime' else runtime.guarded.run_candidate
        with patch.object(runtime.guarded, 'feedback', shared_feedback):
            result = run(llm, job, events)
        if digest(snapshot(root / 'initial-workspace')) != job['shared_candidate_hash']:
            raise ValueError('Shared initial candidate mismatch')
        previous.repair.check_identity(previous.repair.config())
    except Exception as exc:  # noqa: BLE001 - preserve failures and rollback owned candidate
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
        if (root / 'original-workspace').exists():
            runtime.guarded.restore(Path(job['workspace']), root / 'original-workspace', root)
    finally:
        calls = provider.calls if provider else []
        fresh = [c for c in calls if not c.get('replayed')]
        result.update(metrics=llm.metrics() if llm else None, provider_calls=calls, new_model_calls=len(fresh),
                      new_model_tokens=sum(c.get('total_tokens') or 0 for c in fresh))
        previous.write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


def run(output):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    baseline.intact(manifest)
    case = next(c for c in manifest['cases'] if c['task_id'] == TASK)
    if case['split'] != 'development':
        raise ValueError('Development task required')
    shared = baseline.BASE / 'diagnostic-feedback-v1-pilot' / TASK / 'unchanged-feedback'
    if baseline.load(shared / 'worker-result.json')['initial']['status'] != 'completed':
        raise ValueError('Completed recorded first patch required')
    if not baseline.load(shared.parent.parent / 'experiment.json')['complete']:
        raise ValueError('Completed historical pilot required')
    protected = [Path(case[k]).resolve() for k in ('before', 'after', 'checks', 'harness', 'frozen_harness')]
    protected += [source.resolve(), shared.parent.parent.resolve()]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh nonoverlapping output required')
    output.mkdir(parents=True)
    inputs = [source / 'manifest.json', shared.parent.parent / 'experiment.json',
              shared / 'initial-response.txt', shared / 'initial-messages.json', shared / 'feedback-messages.json',
              shared / 'worker-result.json', Path(__file__), Path(runtime.__file__), runtime.PROBE]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in inputs}
    initial_hash = digest(snapshot(shared / 'initial-workspace'))
    report = {'complete': False, 'runs': [], 'protocol': {'name': 'predicate-runtime-v1', 'task': TASK,
              'policies': POLICIES, 'input_hashes': hashes, 'shared_candidate_hash': initial_hash,
              'config': previous.repair.config().to_dict(),
              'change': 'Only append bounded public runtime observations to original second-round feedback',
              'unchanged': 'Identical recorded first patch and original feedback text, seed refresh, system prompt, validators, rollback and budgets',
              'budget': 'Historical first-call usage charged to each task; only two fresh second-round calls total',
              'scope': 'One known development failure; not a full repair-rate or blind experiment'}}

    def intact():
        baseline.intact(manifest)
        if digest(snapshot(shared / 'initial-workspace')) != initial_hash:
            raise ValueError('Historical candidate changed')
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen input changed')

    previous.repair.check_identity(previous.repair.config())
    previous.write_json(output / 'experiment.json', report)
    for policy in POLICIES:
        intact()
        root = output / policy
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                  'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
        job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy,
                   shared_first=str(shared), shared_candidate_hash=initial_hash)
        previous.write_json(root / 'job.json', job)
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.predicate_runtime_compare_v1',
                               '--worker', str(root / 'job.json')], baseline.ROOT, 600,
                              root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(baseline.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        p = root / 'worker-result.json'
        result = baseline.load(p) if p.exists() and not process['timed_out'] else {'status': 'worker_failed'}
        intact()
        grade = root / 'verification'
        grade.mkdir()
        verified = previous.baseline.verify(case, workspace, grade)
        public = previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'final-public')
        frozen = previous.public_check(workspace, case['frozen_harness'], case['package'], case['source_root'], root / 'final-frozen')
        accepted = (result['status'] == 'completed' and verified['passed']
                    and previous.all_pass(public) and previous.all_pass(frozen))
        report['runs'].append({'policy': policy, 'accepted': accepted, 'worker': result,
                               'verification': verified, 'public': public, 'frozen': frozen, 'process': process})
        previous.write_json(output / 'experiment.json', report)
        print(policy, result['status'], 'accepted=', accepted, flush=True)
    report['complete'] = True
    intact()
    previous.write_json(output / 'experiment.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error('Require --output or --worker')
