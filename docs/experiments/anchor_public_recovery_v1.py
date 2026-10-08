"""Paired exact-anchor recovery with pre-certified public boundary checks."""
import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import exact_anchor_recovery_v1 as anchors
from docs.experiments import exact_anchor_report_v1 as witness
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch

previous, policy = anchors.previous, anchors.policy
STRATEGIES = ('anchor-only', 'anchor-public')


def selected(admitted):
    cases = [c for c in previous.cases_from(admitted) if c['task_id'] in anchors.TASKS]
    if len(cases) != 3:
        raise ValueError('Require three fixed known anchor failures')
    return cases


def check_harness(job):
    harness = Path(job['harness'])
    if digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Public harness changed')
    return harness


def public_feedback(job, root):
    harness = check_harness(job)
    return {'provenance': 'handwritten public API checks certified before inference; not private grading',
            'test_code': (harness / 'test_admission.py').read_text(encoding='utf-8'),
            'observations': policy.diagnostic(job['public_initial'], root.parent / 'public-initial',
                                             Path(job['workspace']), harness)}


def certify(admitted, output):
    cases = selected(admitted)
    previous.fresh_output(output, cases)
    report = {'complete': False, 'cases': [], 'model_calls': 0,
              'admission_hash': policy.admission.history.sha(admitted),
              'adapter_hash': policy.admission.history.sha(Path(__file__)),
              'authoring': 'known failures; public checks hand authored and informed by prior patch audit, not blind'}
    for case in cases:
        root = output / case['task_id']
        harness = root / 'checks'
        harness.mkdir(parents=True)
        code = previous.examples.code(case['task_id'])
        if case['task_id'] == 'more-split-empty':
            # Keep the prior list/control examples and add the independent iterator witness.
            code += witness.WITNESS.replace('class Reproduce(', 'class IteratorReproduce(').replace(
                'class Preserve(', 'class IteratorPreserve(')
            # Discovery selects group classes by name: merge witness methods into each group.
            code += '\nReproduce.test_empty_iterators_produce_no_groups = IteratorReproduce.test_empty_iterators_produce_no_groups\n'
            code += 'Preserve.test_nonempty_iterators_remain_unsplit = IteratorPreserve.test_nonempty_iterators_remain_unsplit\n'
        compile(code, 'test_admission.py', 'exec')
        (harness / 'test_admission.py').write_text(code, encoding='utf-8')
        outcomes = {}
        for label in ('before', 'after'):
            if digest(snapshot(Path(case[label]))) != case[label + '_hash']:
                raise ValueError('Frozen source changed')
            outcomes[label] = policy.public_check(case[label], harness, case['package'], case['source_root'], root / label)
        row = {'task_id': case['task_id'], 'certified': policy.certified(outcomes), 'outcomes': outcomes,
               'harness': str(harness.resolve()), 'harness_hash': digest(snapshot(harness)),
               'description_hash': hashlib.sha256(case['description'].encode()).hexdigest()}
        report['cases'].append(row)
        policy.write_json(output / 'certificates.json', report)
        print(case['task_id'], 'certified:', row['certified'], flush=True)
    report['complete'] = all(r['certified'] for r in report['cases'])
    policy.write_json(output / 'certificates.json', report)


def resubmit(llm, job, root, feedback):
    workspace = Path(job['workspace'])
    evidence = job['evidence']
    policy.repair.validate_evidence(workspace, job['allowed_files'], evidence)
    messages = [{'role': 'system', 'content': policy.repair.patcher.SYMBOL_SYSTEM +
                 ' The previous transaction was rejected and no edits were committed. '
                 'Resubmit a complete patch against the unchanged current source. '
                 'For ambiguous anchors include more exact surrounding source (for example a unique function header). '
                 'For sequential conflicts do not replace an already replaced anchor twice. '
                 'Do not use line-number edits, fuzzy matching, or relax the version/unique-match rules. '
                 'Also satisfy the certified public checks below; these are not the private final grader. '
                 'Preserve normal behavior and iterator semantics. Return one complete patch.'},
                {'role': 'user', 'content': json.dumps({'description': job['description'],
                 'allowed_files': job['allowed_files'], 'fragments': evidence,
                 'edit_transaction_feedback': feedback, 'public_check_feedback': public_feedback(job, root)}, ensure_ascii=False)}]
    policy.write_json(root / 'recovery-messages.json', messages)
    result = {'status': 'invalid_patch'}
    try:
        response = llm.chat(messages, tools=[])
        (root / 'recovery-response.txt').write_text(response.content, encoding='utf-8')
        if response.tool_calls:
            raise ValueError('Unexpected tool call')
        stage = root / 'recovery-staging'
        shutil.copytree(workspace, stage)
        edited = apply_symbol_patch(policy.baseline.envelope.normalize(response.content), stage,
                                    job['allowed_files'], evidence)
        for name in edited:
            compile((stage / name).read_bytes(), name, 'exec')
        for name in edited:
            (workspace / name).write_bytes((stage / name).read_bytes())
        result.update(status='completed', edited_files=edited)
    except Exception as exc:  # noqa: BLE001 - preserve failed calls and transactions
        result.update(status=str(exc) if isinstance(exc, policy.baseline.InvalidCompletion) else
                      'budget_exceeded' if isinstance(exc, policy.baseline.BudgetExceeded) else 'invalid_patch',
                      error=f'{type(exc).__name__}: {exc}')
    return result



def retain_checked(job, root, result):
    """A syntactically applied correction is retained only if both public groups pass."""
    if result['status'] != 'completed':
        return result
    workspace = Path(job['workspace'])
    result['retained'] = False
    try:
        harness = check_harness(job)
        outcome = policy.public_check(workspace, harness, job['package'], job['source_root'], root / 'public-corrected')
        result['public_corrected'] = outcome
        result['retained'] = policy.all_pass(outcome)
    except Exception as exc:  # noqa: BLE001 - failed verification must restore the original
        result['public_error'] = f'{type(exc).__name__}: {exc}'
    if not result['retained']:
        for name in job['allowed_files']:
            (workspace / name).write_bytes((root.parent / 'initial-workspace' / name).read_bytes())
        result['status'] = 'public_checks_failed'
    return result


def worker(path):
    job, root = previous.load(path), path.parent
    events = Events(root / 'trace.jsonl', 'anchor-public-recovery-v1')
    provider = llm = None
    report = {'status': 'agent_error', 'branches': {}}
    try:
        policy.repair.check_identity(policy.repair.config())
        workspace = Path(job['workspace'])
        harness = check_harness(job)
        original = digest(snapshot(workspace))
        provider = policy.Provider('qwen', events)
        llm = policy.CheckedBudgetLLM(provider, policy.repair.config(), events)
        first = policy.request(llm, workspace, job, job['evidence'], root, 'initial')
        report.update(initial=first, initial_metrics=llm.metrics(), initial_provider_calls=copy.deepcopy(provider.calls))
        shutil.copytree(workspace, root / 'initial-workspace')
        qualified = first['status'] == 'invalid_patch' and first.get('error', '').endswith('Old text must match exactly once')
        feedback = None
        if qualified:
            if digest(snapshot(workspace)) != original:
                raise ValueError('Rejected transaction mutated workspace')
            feedback = anchors.diagnose((root / 'initial-response.txt').read_text(encoding='utf-8'), workspace,
                                       job['allowed_files'], job['evidence'])
        report['diagnosis'] = feedback
        if feedback:
            job['public_initial'] = policy.public_check(workspace, harness, job['package'], job['source_root'],
                                                        root / 'public-initial')
            report['public_initial'] = job['public_initial']
        for strategy in STRATEGIES:
            branch = root / strategy
            branch.mkdir()
            candidate = branch / 'workspace'
            shutil.copytree(workspace, candidate)
            branch_job = dict(job, workspace=str(candidate))
            branch_events = Events(branch / 'trace.jsonl', strategy)
            branch_provider = policy.Provider('qwen', branch_events)
            # Copy scalar budget counters, preserving the identical first-call charge in each arm.
            branch_llm = copy.copy(llm)
            branch_llm.inner, branch_llm.events = branch_provider, branch_events
            try:
                if feedback:
                    result = (anchors.resubmit if strategy == 'anchor-only' else resubmit)(
                        branch_llm, branch_job, branch, feedback)
                    if strategy == 'anchor-public':
                        result = retain_checked(branch_job, branch, result)
                else:
                    result = dict(first, recovery_skipped='initial_not_recoverable')
                result['metrics'] = branch_llm.metrics()
                result['provider_calls'] = branch_provider.calls  # Only new calls; shared first stored separately.
                report['branches'][strategy] = result
            finally:
                branch_provider.client.close()
        policy.repair.check_identity(policy.repair.config())
        report['status'] = 'completed'
    except Exception as exc:  # noqa: BLE001 - preserve failed experiments
        report.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        policy.write_json(root / 'worker-result.json', events.clean(report))
        if provider:
            provider.client.close()


def run(admitted, certificates, output):
    cases, certs = selected(admitted), previous.load(certificates)
    by_id = {c['task_id']: c for c in certs['cases']}
    if (not certs['complete'] or len(certs['cases']) != 3 or set(by_id) != anchors.TASKS or
            certs['admission_hash'] != policy.admission.history.sha(admitted) or
            certs['adapter_hash'] != policy.admission.history.sha(Path(__file__)) or
            not all(c['certified'] for c in by_id.values())):
        raise ValueError('Require unchanged complete public certificates')
    previous.fresh_output(output, cases, [c['harness'] for c in by_id.values()])
    inputs = {str(p.resolve()): policy.admission.history.sha(p) for p in (admitted, certificates)}
    inputs.update({str(Path(m.__file__).resolve()): policy.admission.history.sha(Path(m.__file__))
                   for name, m in list(sys.modules.items()) if name.startswith(('docs.experiments.', 'evals.', 'corecoder.'))
                   and getattr(m, '__file__', None) and Path(m.__file__).suffix == '.py'})
    observations = []
    for case in cases:
        index = policy.baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observations.append(dict(task_id=case['task_id'], **policy.retrieval.retrieve(index, case['description'])))
    policy.write_json(output / 'observations.json', observations)
    inputs[str(output / 'observations.json')] = policy.admission.history.sha(output / 'observations.json')
    report = {'complete': False, 'runs': [], 'actual_calls': [], 'protocol': {
        'name': 'anchor-public-recovery-v1', 'scope': 'three selected known failures; diagnostic, not heldout',
        'config': policy.repair.config().to_dict(), 'max_calls_per_arm': 2, 'token_budget_per_arm': 15000,
        'comparison': 'shared fresh first patch; anchor-only vs anchor+certified public feedback in sole resubmission',
        'retention': 'public arm retains correction only if Reproduce and Preserve pass; otherwise restores first snapshot',
        'accounting': 'actual calls count shared first once plus both new resubmissions; per-arm totals overlap',
        'unique_match_version_checks': 'unchanged', 'no_private_grader_input': True, 'frozen_inputs': inputs}}

    def frozen():
        policy.repair.check_identity(policy.repair.config())
        if any(policy.admission.history.sha(Path(p)) != h for p, h in inputs.items()):
            raise ValueError('Frozen runtime/input changed')
        for case in cases:
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source/grader changed')
            cert = by_id[case['task_id']]
            if (digest(snapshot(Path(cert['harness']))) != cert['harness_hash'] or
                    cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest()):
                raise ValueError('Public harness/description changed')

    def save():
        report['summary'] = {s: policy.baseline.summarize([r for r in report['runs'] if r['policy'] == s])
                             for s in STRATEGIES}
        report['actual_usage'] = {'model_calls': len(report['actual_calls']),
                                 'tokens': sum(c.get('total_tokens') or 0 for c in report['actual_calls']),
                                 'missing_usage_calls': sum(not c.get('total_tokens') for c in report['actual_calls'])}
        policy.write_json(output / 'experiment.json', report)

    frozen()
    save()
    for case, observed in zip(cases, observations):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        job = previous.job_for(case, workspace, observed['evidence'], by_id[case['task_id']])
        path = root / 'job.json'
        policy.write_json(path, job)
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.anchor_public_recovery_v1', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = previous.load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
            'status': 'agent_error', 'branches': {}}
        report['actual_calls'].extend(result.get('initial_provider_calls', []))
        for strategy in STRATEGIES:
            branch = root / strategy
            branch.mkdir(exist_ok=True)
            source = branch / 'workspace'
            chosen = result['branches'].get(strategy, {'status': 'agent_error', 'metrics': None})
            report['actual_calls'].extend(chosen.get('provider_calls', []))
            grade = root / ('grade-' + strategy)
            grade.mkdir()
            verified = policy.baseline.verify(case, source if source.exists() else workspace, grade)
            checked = policy.public_check(source if source.exists() else workspace, Path(job['harness']),
                                          case['package'], case['source_root'], root / ('public-final-' + strategy))
            accepted = chosen['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'split': 'diagnostic', 'repo': case['repo'],
                                  'policy': strategy, 'worker': chosen, 'verification': verified,
                                  'public_evaluation': checked, 'public_passed': policy.all_pass(checked),
                                  'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification'
                                  if chosen['status'] == 'completed' else chosen['status'], 'process': process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'], flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 6
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--certify', type=Path)
    parser.add_argument('--certificates', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.admission and args.certify:
        certify(args.admission.resolve(), args.certify.resolve())
    elif args.admission and args.certificates and args.output:
        run(args.admission.resolve(), args.certificates.resolve(), args.output.resolve())
    else:
        parser.error('Provide worker, certification or run arguments')
