"""Fresh paired development comparison; shared first inference, bounded arm budgets."""
import argparse
import copy
import json
import os
import shutil
import sys
import time
from pathlib import Path

from docs.experiments import frozen_feedback_replay_v1 as replay
from docs.experiments import frozen_feedback_v1 as guarded
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = guarded.previous
POLICIES = ('public-feedback', 'frozen-feedback')


class SharedInitial:
    """Replay only identical first requests, including original usage and rejection metadata."""
    def __init__(self):
        self.request = self.response = self.call = self.error = None

    def chat(self, provider, messages, tools):
        request = json.dumps([messages, tools], ensure_ascii=False, sort_keys=True)
        if self.request is None:
            self.request = request
            try:
                self.response = provider.chat(messages, tools)
                return self.response
            except Exception as exc:
                self.error = type(exc).__name__
                raise
            finally:
                if provider.calls:
                    self.call = copy.deepcopy(provider.calls[-1])
        if request != self.request:
            raise ValueError('Paired initial requests differ')
        if self.call is not None:
            provider.calls.append(dict(self.call, shared_initial_replay=True))
        if self.error:
            raise RuntimeError('Shared initial provider failure: ' + self.error)
        if self.response is None:
            raise ValueError('Missing shared initial response')
        return copy.deepcopy(self.response)


class PairedProvider:
    def __init__(self, provider, shared):
        self.inner, self.shared = provider, shared
        self.calls = provider.calls
        self.model = provider.model

    def chat(self, messages, tools=None):
        if not self.calls:
            return self.shared.chat(self.inner, messages, tools)
        return self.inner.chat(messages, tools)


def control(llm, job, events):
    """Original public-feedback-v2 decisions; keep failing initial for independent scoring."""
    root, workspace = events.path.parent, Path(job['workspace'])
    guarded.validate(job, root)
    result = {'status': 'agent_error', 'feedback_attempts': 0, 'published': False,
              'correction_retained': False}
    first = previous.request(llm, workspace, job, job['evidence'], root, 'initial')
    result.update(status=first['status'], initial=first, initial_metrics=llm.metrics().copy())
    shutil.copytree(workspace, root / 'initial-workspace')
    if first['status'] == 'completed':
        checked = previous.public_check(workspace, job['harness'], job['package'], job['source_root'],
                                        root / 'public-initial')
        result['public_initial'] = checked
        selected = checked
        if not previous.all_pass(checked) and guarded.executable({'public': checked}):
            evidence = previous.refresh_seeds(workspace, job['allowed_files'], job['evidence'])['evidence']
            feedback = {'provenance': 'certified handwritten public-description checks; not private scoring',
                        'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
                        'observations': previous.diagnostic(checked, root / 'public-initial', workspace,
                                                            Path(job['harness']))}
            result['feedback_attempts'] = 1
            second = previous.request(llm, workspace, job, evidence, root, 'feedback', feedback)
            result['correction'] = second
            if second['status'] == 'completed':
                corrected = previous.public_check(workspace, job['harness'], job['package'], job['source_root'],
                                                  root / 'public-corrected')
                result['public_corrected'] = corrected
                result['correction_retained'] = previous.all_pass(corrected)
                if result['correction_retained']:
                    selected = corrected
            if not result['correction_retained']:
                guarded.restore(workspace, root / 'initial-workspace', root)
        result['published'] = previous.all_pass(selected)
    result['metrics'] = llm.metrics()
    result['final_source_hash'] = digest(snapshot(workspace))
    result['original_restored'] = result['final_source_hash'] == job['original_hash']
    return result


def worker(path):
    jobs = replay.load(path)
    shared = SharedInitial()
    previous.repair.check_identity(previous.repair.config())
    for policy in POLICIES:
        job = jobs[policy]
        root = Path(job['workspace']).parent
        events = Events(root / 'trace.jsonl', policy)
        provider = previous.Provider('qwen', events)
        paired = PairedProvider(provider, shared)
        llm = previous.CheckedBudgetLLM(paired, previous.repair.config(), events)
        started = time.monotonic()
        try:
            result = (control if policy == POLICIES[0] else guarded.run_candidate)(llm, job, events)
            previous.repair.check_identity(previous.repair.config())
        except Exception as exc:  # noqa: BLE001 - preserve failures as failed arms
            result = {'status': 'agent_error', 'published': False, 'error_type': type(exc).__name__,
                      'metrics': llm.metrics()}
            if (root / 'original-workspace').exists():
                guarded.restore(Path(job['workspace']), root / 'original-workspace', root)
        finally:
            provider.client.close()
        result.update(provider_calls=provider.calls, seconds=round(time.monotonic() - started, 4),
                      actual_model_calls=sum(not c.get('shared_initial_replay') for c in provider.calls))
        previous.write_json(root / 'worker-result.json', events.clean(result))
    first, second = [digest(snapshot(Path(jobs[p]['workspace']).parent / 'initial-workspace')) for p in POLICIES]
    if first != second:
        raise ValueError('Shared first answers produced different initial source')


def summarize(rows):
    return {policy: {
        'tasks': len(items := [r for r in rows if r['policy'] == policy]),
        'independent_passed': sum(r['accepted'] for r in items),
        'target_passed': sum(r['verification']['groups']['Target']['passed'] for r in items),
        'controls_passed': sum(r['verification']['groups']['Controls']['passed'] for r in items),
        'retained': sum(r['worker'].get('published', False) for r in items),
        'false_retained': [r['task_id'] for r in items if r['worker'].get('published') and not r['accepted']],
        'feedback_attempts': sum(r['worker'].get('feedback_attempts', 0) for r in items),
        'corrections_retained': sum(r['worker'].get('correction_retained', False) for r in items),
        'budget_accounted_tokens': sum(r['worker']['metrics']['budget_accounted_tokens'] for r in items),
        'model_calls_including_shared_initial': sum(r['worker']['metrics']['llm_calls'] for r in items),
        'actual_model_calls': sum(r['worker']['actual_model_calls'] for r in items),
        'worker_seconds_excluding_shared_initial_inference_for_second_arm': round(sum(r['worker']['seconds'] for r in items), 4),
    } for policy in POLICIES}


def run(args):
    plan, audit = replay.prepare(args.audit, args.admission, args.development, args.heldout, args.certificates)
    plan = [item for item in plan if item['case']['split'] == 'development']
    if len(plan) != 27:
        raise ValueError('Require fixed 27 certified development tasks')
    output = args.output.resolve()
    protected = [Path(item['case'][k]).resolve() for item in plan for k in ('before', 'after', 'checks')]
    protected += [Path(item['certificate']['harness']).resolve() for item in plan]
    protected += [Path(item['guard']['harness']).resolve() for item in plan]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh output outside frozen sources/checks required')
    previous.repair.check_identity(previous.repair.config())
    output.mkdir(parents=True)
    paths = [args.audit, args.admission, args.development, args.heldout, *args.certificates,
             Path(__file__), Path(guarded.__file__), Path(previous.__file__), Path(replay.__file__)]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in paths}
    report = {'complete': False, 'runs': [], 'protocol': {
        'tasks': 27, 'split': 'certified development only; no heldout inference',
        'excluded_development': [c['task_id'] for c in audit['cases']
                                 if not c['certified'] and c['original_split'] == 'development'],
        'model_digest': previous.repair.MODEL_DIGEST, 'config': previous.repair.config().to_dict(),
        'input_hashes': hashes, 'private_selection': False,
        'pairing': 'shared fresh first answer; independently generated second answers; control then candidate',
        'budget': 'two calls and 15000 tokens per arm, including shared initial usage in both arms',
        'accounting': 'actual calls/usage count shared initial once; latency excludes shared inference in second arm',
        'limits': 'development experiment, not blind; no default Agent/API changes'}}

    def frozen():
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen comparison inputs changed')
        for item in plan:
            case = item['case']
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source or grading checks changed')
            for cert in (item['certificate'], item['guard']):
                if digest(snapshot(Path(cert['harness']))) != cert['harness_hash']:
                    raise ValueError('Certified harness changed')

    def save():
        report['summary'] = summarize(report['runs'])
        rows = {p: {r['task_id']: r for r in report['runs'] if r['policy'] == p} for p in POLICIES}
        report['gained'] = [t for t in rows[POLICIES[0]] if not rows[POLICIES[0]][t]['accepted'] and rows[POLICIES[1]][t]['accepted']]
        report['lost'] = [t for t in rows[POLICIES[0]] if rows[POLICIES[0]][t]['accepted'] and not rows[POLICIES[1]][t]['accepted']]
        if report['complete']:
            stats = report['summary']
            improved = stats[POLICIES[1]]['independent_passed'] - stats[POLICIES[0]]['independent_passed'] >= 2
            safe = stats[POLICIES[1]]['controls_passed'] >= stats[POLICIES[0]]['controls_passed']
            report['decision'] = 'development_gain_expand_validation' if improved and safe else 'stop_repair_gain_claim_keep_validation_optional'
        calls = [c for r in report['runs'] for c in r['worker']['provider_calls'] if not c.get('shared_initial_replay')]
        report['actual_usage'] = {'calls': len(calls), 'tokens': sum(c.get('total_tokens') or 0 for c in calls),
                                  'provider_seconds': round(sum(c['seconds'] for c in calls), 4)}
        previous.write_json(output / 'experiment.json', report)

    for item in plan:
        frozen()
        case, cert, guard = item['case'], item['certificate'], item['guard']
        root = output / case['task_id']
        root.mkdir()
        jobs = {}
        for policy in POLICIES:
            workspace = root / policy / 'workspace'
            shutil.copytree(case['before'], workspace)
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root')}
            job.update(workspace=str(workspace), evidence=item['evidence'], original_hash=case['before_hash'],
                       description_hash=cert['description_hash'], harness=cert['harness'], harness_hash=cert['harness_hash'],
                       frozen_harness=guard['harness'], frozen_harness_hash=guard['harness_hash'])
            jobs[policy] = job
        path = root / 'jobs.json'
        previous.write_json(path, jobs)
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.frozen_feedback_compare_v1', '--worker', str(path)],
                              previous.ROOT, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(previous.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        if process['returncode'] != 0 or process['timed_out']:
            raise RuntimeError('Paired worker failed: ' + case['task_id'] + '; inspect worker logs')
        for policy in POLICIES:
            arm = root / policy
            result = replay.load(arm / 'worker-result.json')
            grading = arm / 'verification'
            grading.mkdir()
            verified = previous.baseline.verify(case, arm / 'workspace', grading)
            accepted = result['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'policy': policy,
                                   'worker': result, 'verification': verified, 'accepted': accepted})
        save()
        print(case['task_id'], report['runs'][-2]['accepted'], '->', report['runs'][-1]['accepted'], flush=True)
    frozen()
    previous.repair.check_identity(previous.repair.config())
    report['complete'] = len(report['runs']) == 54
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    for name in ('audit', 'admission', 'development', 'heldout', 'output'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--certificates', nargs=2, type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif all(getattr(args, n) for n in ('audit', 'admission', 'development', 'heldout', 'output', 'certificates')):
        run(args)
    else:
        parser.error('Provide --worker or all frozen inputs and --output')
