"""Paired one-shot / bounded self-review repair; private grading happens afterwards."""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from docs.experiments import class_scoped_retrieval_v1 as retrieval
from docs.experiments import expanded_baseline_v2 as baseline
from docs.experiments.provider_compare_worker_v1 import CheckedBudgetLLM, InvalidCompletion, Provider
from evals.process import run_process
from evals.runtime import BudgetExceeded, Events
from evals.symbol_context import apply_symbol_patch

ROOT = baseline.ROOT
POLICIES = ('single', 'self-review')
REVIEW_INSTRUCTION = (
    'Review the proposed patch against the issue and ORIGINAL source fragments. '
    'Check the stated failing behavior, boundary cases, default/explicit argument distinctions, '
    'and preservation of existing behavior. Do not invent an API or assume test results. '
    'Return exactly {"decision":"keep"} if the patch needs no change; otherwise return '
    'a complete replacement patch in the original edits JSON format. All old snippets must '
    'match ORIGINAL fragments, never the proposed edited version. No prose or extra fields.'
)


def inputs(job):
    """Explicit public projection: never serialize a caller's entire job."""
    return {key: job[key] for key in ('description', 'allowed_files', 'evidence')}


def messages(job, proposed=None, error=None):
    public = inputs(job)
    data = {'description': public['description'], 'allowed_files': public['allowed_files'],
            'fragments': public['evidence']}
    system = baseline.repair.patcher.SYMBOL_SYSTEM
    if proposed is not None:
        system += '\n' + REVIEW_INSTRUCTION
        data['proposed_patch'] = proposed
        data['structural_error'] = error
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]


def apply(content, original, destination, job):
    """Stage against original bytes. Rejected partial or syntactically invalid edits are discarded."""
    shutil.copytree(original, destination)
    try:
        edited = apply_symbol_patch(baseline.envelope.normalize(content), destination,
                                    job['allowed_files'], job['evidence'])
        for name in edited:
            compile((destination / name).read_bytes(), name, 'exec')
        return {'status': 'completed', 'edited_files': edited}
    except (ValueError, TypeError, KeyError, SyntaxError, OSError) as exc:
        shutil.rmtree(destination)
        shutil.copytree(original, destination)
        return {'status': 'invalid_patch', 'error': f'{type(exc).__name__}: {exc}'}


def is_keep(content):
    try:
        return json.loads(baseline.envelope.normalize(content)) == {'decision': 'keep'}
    except (ValueError, TypeError):
        return False


def copy_initial(initial, final):
    if final.exists():
        shutil.rmtree(final)
    shutil.copytree(initial, final)


def generate(llm, job, events):
    started = time.perf_counter()
    original = Path(job['workspace'])
    initial = events.path.parent / 'single'
    final = events.path.parent / 'self-review'
    baseline.repair.validate_evidence(original, job['allowed_files'], job['evidence'])
    request = messages(job)
    (events.path.parent / 'messages.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
    first = llm.chat(request, tools=[])
    if first.tool_calls:
        raise ValueError('Unexpected tool call')
    (events.path.parent / 'response.txt').write_text(events.clean(first.content), encoding='utf-8')
    initial_result = apply(first.content, original, initial, job)
    first_metrics = dict(llm.metrics())
    result = {'initial': dict(initial_result, metrics=first_metrics, seconds=round(time.perf_counter() - started, 4)),
              'prompt_hash': hashlib.sha256(json.dumps(request, ensure_ascii=False).encode()).hexdigest()}
    # Safe fallback is selected by public structural checks only, never by private grader results.
    copy_initial(initial, final)
    result['final'] = dict(initial_result)
    review_request = messages(job, first.content, initial_result.get('error'))
    (events.path.parent / 'review-messages.json').write_text(json.dumps(review_request, indent=2), encoding='utf-8')
    try:
        second = llm.chat(review_request, tools=[])
        if second.tool_calls:
            raise InvalidCompletion('unexpected_tool_call')
        (events.path.parent / 'review-response.txt').write_text(events.clean(second.content), encoding='utf-8')
        if is_keep(second.content):
            result['review_status'] = 'kept_initial'
        else:
            candidate = events.path.parent / 'review-staging'
            reviewed = apply(second.content, original, candidate, job)
            result['review_status'] = reviewed['status']
            result['review_candidate'] = reviewed
            if reviewed['status'] == 'completed':
                copy_initial(candidate, final)
                result['final'] = reviewed
            else:
                result['review_status'] = 'rejected_invalid_review_kept_initial'
    except (BudgetExceeded, InvalidCompletion) as exc:
        result['review_status'] = str(exc)
        result['review_stopped'] = type(exc).__name__
    result['final']['metrics'] = llm.metrics()
    result['final']['seconds'] = round(time.perf_counter() - started, 4)
    return result


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    events = Events(path.parent / 'trace.jsonl', 'patch-self-review-v1')
    provider = llm = None
    result = {'status': 'agent_error'}
    try:
        baseline.repair.check_identity(baseline.repair.config())
        provider = Provider('qwen', events)
        llm = CheckedBudgetLLM(provider, baseline.repair.config(), events)
        result = generate(llm, job, events)
        result['status'] = 'completed'
        baseline.repair.check_identity(baseline.repair.config())
    except Exception as exc:  # noqa: BLE001 - preserve infrastructure failure, never claim repair success
        result.update(status='agent_error', error_type=type(exc).__name__)
    finally:
        result['metrics'] = llm.metrics() if llm else None
        result['provider_calls'] = provider.calls if provider else []
        (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')
        if provider:
            provider.client.close()


def classify(row):
    if row['accepted']:
        return 'passed'
    if row['worker']['status'] != 'completed':
        return row['worker']['status']
    verification = row['verification']
    if verification.get('scope_violations'):
        return 'scope_violation'
    groups = verification.get('groups') or {}
    if not groups.get('Controls', {}).get('passed'):
        return 'control_regression'
    return 'target_failed'


def summary(rows):
    from collections import Counter
    report = {}
    for policy in POLICIES:
        selected = [row for row in rows if row['policy'] == policy]
        report[policy] = baseline.summarize(selected)
        report[policy]['failure_categories'] = dict(Counter(classify(row) for row in selected))
    pairs = {row['task_id']: {} for row in rows}
    for row in rows:
        pairs[row['task_id']][row['policy']] = row
    complete = [pair for pair in pairs.values() if set(pair) == set(POLICIES)]
    report['paired'] = {
        'tasks': len(complete),
        'gained': sum(not p['single']['accepted'] and p['self-review']['accepted'] for p in complete),
        'lost': sum(p['single']['accepted'] and not p['self-review']['accepted'] for p in complete),
    }
    return report


def run(admitted, output):
    data = json.loads(admitted.read_text(encoding='utf-8'))
    all_cases = data['cases']
    cases = [case for case in all_cases if case['split'] == 'development']
    if not data['complete'] or len(all_cases) != 50 or len({c['task_id'] for c in all_cases}) != 50 or len(cases) != 30:
        raise ValueError('Require frozen 50-task admission with 30 development tasks')
    if output.exists() or any(output.is_relative_to(Path(c[p]).resolve()) for c in all_cases for p in ('before', 'after', 'checks')):
        raise ValueError('Fresh output outside frozen inputs required')
    baseline.repair.check_identity(baseline.repair.config())
    output.mkdir(parents=True)
    observed = []
    for case in cases:
        index = baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observed.append(retrieval.retrieve(index, case['description']))
    observation_path = output / 'observations.json'
    observation_path.write_text(json.dumps(observed, indent=2), encoding='utf-8')
    frozen_files = [admitted, observation_path, Path(__file__), Path(retrieval.__file__), Path(baseline.__file__)]
    hashes = {str(p): baseline.admission.history.sha(p) for p in frozen_files}
    report = {'complete': False, 'runs': [], 'protocol': {
        'name': 'patch-self-review-v1', 'model_digest': baseline.repair.MODEL_DIGEST,
        'config': baseline.repair.config().to_dict(), 'development_only': True,
        'max_calls': 2, 'shared_initial_response': True, 'shared_budget': True,
        'private_grading_after_both_candidates': True, 'review_selection': 'structure only; no private tests',
        'promotion_gate': 'net >=2 repairs; no newly regressed previously passing Controls',
        'comparison_limit': 'review adds one call and proposed-patch context; actual cost must be reported',
        'inputs_sha256': hashes}}

    def frozen():
        baseline.repair.check_identity(baseline.repair.config())
        if any(baseline.admission.history.sha(Path(p)) != value for p, value in hashes.items()):
            raise ValueError('Frozen protocol changed')
        for case in cases:
            for field in ('before', 'after', 'checks'):
                if baseline.digest(baseline.snapshot(Path(case[field]))) != case[field + '_hash']:
                    raise ValueError('Frozen source or checks changed')

    def save():
        report['summary'] = summary(report['runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    frozen()
    save()
    for case, evidence in zip(cases, observed):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'original'
        shutil.copytree(case['before'], workspace)
        job = {'workspace': str(workspace), 'description': case['description'],
               'allowed_files': case['allowed_files'], 'evidence': evidence['evidence']}
        job_path = root / 'job.json'
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.patch_self_review_v1', '--worker', str(job_path)],
                              workspace, 600, root / 'stdout.txt', root / 'stderr.txt',
                              dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
        for policy, key in zip(POLICIES, ('initial', 'final')):
            candidate = root / policy
            branch = result.get(key, {'status': 'agent_error', 'metrics': result.get('metrics')})
            if process['timed_out'] or process['returncode'] != 0 or result.get('status') != 'completed':
                branch = {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': result.get('metrics')}
            if not candidate.exists():
                shutil.copytree(case['before'], candidate)
            logs = root / (policy + '-verification')
            logs.mkdir()
            verification = baseline.verify(case, candidate, logs)
            accepted = branch['status'] == 'completed' and verification['passed']
            row = {'task_id': case['task_id'], 'repo': case['repo'], 'split': 'development', 'policy': policy,
                   'worker': branch, 'verification': verification, 'accepted': accepted,
                   'process': dict(process, seconds=branch.get('seconds', process['seconds'])),
                   'status': 'passed' if accepted else 'failed_verification' if branch['status'] == 'completed' else branch['status'],
                   'review_status': result.get('review_status')}
            report['runs'].append(row)
            print(case['task_id'], policy, classify(row), flush=True)
        save()
    frozen()
    report['complete'] = len(report['runs']) == 60
    pairs = {c['task_id']: [r for r in report['runs'] if r['task_id'] == c['task_id']] for c in cases}
    new_regressions = [key for key, pair in pairs.items()
                       if (pair[0]['verification'].get('groups') or {}).get('Controls', {}).get('passed')
                       and not (pair[1]['verification'].get('groups') or {}).get('Controls', {}).get('passed')]
    paired = summary(report['runs'])['paired']
    report['gate'] = {'eligible': paired['gained'] - paired['lost'] >= 2 and not new_regressions,
                      'new_control_regressions': new_regressions}
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.admission and args.output:
        run(args.admission.resolve(), args.output.resolve())
    else:
        parser.error('Provide --worker, or --admission and --output')
