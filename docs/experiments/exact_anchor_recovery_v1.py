"""One error-driven resubmission for rejected exact-anchor patch transactions."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import public_feedback_heldout_v1 as previous
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch

policy = previous.policy
TASKS = {'more-falsy-exception', 'more-seekable-zero', 'more-split-empty'}


def diagnose(content, workspace, allowed, evidence):
    """Replay in memory, reporting the first failure without altering any source."""
    policy.repair.validate_evidence(workspace, allowed, evidence)
    parsed = json.loads(policy.baseline.envelope.normalize(content))
    if not isinstance(parsed, dict) or set(parsed) != {'edits'} or not isinstance(parsed['edits'], list):
        return None
    if len(parsed['edits']) > 20:
        return None
    staged = {}
    for number, edit in enumerate(parsed['edits']):
        if (not isinstance(edit, dict) or set(edit) != {'file', 'old', 'new'} or
                not all(isinstance(v, str) for v in edit.values()) or not edit['old']):
            return None
        name = edit['file']
        rows = [r for r in evidence if r['path'] == name]
        if name not in allowed or not rows or not any(edit['old'] in r['content'] for r in rows):
            return None
        text = staged.get(name, (workspace / name).read_bytes().decode('utf-8'))
        count = text.count(edit['old'])
        if count != 1:
            return {'error': 'old_text_not_unique', 'edit_index': number, 'file': name,
                    'sequential_match_count': count,
                    'original_match_count': (workspace / name).read_bytes().decode('utf-8').count(edit['old']),
                    'displayed_owners': [r['symbol'] for r in rows if edit['old'] in r['content']],
                    'none_committed': True, 'rejected_patch': parsed}
        staged[name] = text.replace(edit['old'], edit['new'], 1)
    return None


def resubmit(llm, job, root, feedback):
    workspace = Path(job['workspace'])
    evidence = job['evidence']
    policy.repair.validate_evidence(workspace, job['allowed_files'], evidence)
    messages = [{'role': 'system', 'content': policy.repair.patcher.SYMBOL_SYSTEM +
                 ' The previous transaction was rejected and no edits were committed. '
                 'Resubmit a complete patch against the unchanged current source. '
                 'For ambiguous anchors include more exact surrounding source (for example a unique function header). '
                 'For sequential conflicts do not replace an already replaced anchor twice. '
                 'Do not use line-number edits, fuzzy matching, or relax the version/unique-match rules.'},
                {'role': 'user', 'content': json.dumps({'description': job['description'],
                 'allowed_files': job['allowed_files'], 'fragments': evidence,
                 'edit_transaction_feedback': feedback}, ensure_ascii=False)}]
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


def worker(path):
    job = previous.load(path)
    root = path.parent
    events = Events(root / 'trace.jsonl', 'exact-anchor-recovery-v1')
    provider = llm = None
    result = {'status': 'agent_error', 'recovery_attempts': 0}
    try:
        policy.repair.check_identity(policy.repair.config())
        workspace = Path(job['workspace'])
        initial_hash = digest(snapshot(workspace))
        provider = policy.Provider('qwen', events)
        llm = policy.CheckedBudgetLLM(provider, policy.repair.config(), events)
        first = policy.request(llm, workspace, job, job['evidence'], root, 'initial')
        result.update(status=first['status'], initial=first, initial_metrics=llm.metrics().copy())
        shutil.copytree(workspace, root / 'initial-workspace')
        if first['status'] == 'invalid_patch' and first.get('error', '').endswith('Old text must match exactly once'):
            if digest(snapshot(workspace)) != initial_hash:
                raise ValueError('Rejected initial patch mutated workspace')
            feedback = diagnose((root / 'initial-response.txt').read_text(encoding='utf-8'), workspace,
                                job['allowed_files'], job['evidence'])
            result['diagnosis'] = feedback
            if feedback:
                result['recovery_attempts'] = 1
                result['recovery'] = resubmit(llm, job, root, feedback)
                result['status'] = result['recovery']['status']
        policy.repair.check_identity(policy.repair.config())
    except Exception as exc:  # noqa: BLE001 - record every failed experiment branch
        result.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics'] = llm.metrics() if llm else None
        result['provider_calls'] = provider.calls if provider else []
        policy.write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


def run(admitted, output):
    cases = [c for c in previous.cases_from(admitted) if c['task_id'] in TASKS]
    if len(cases) != 3:
        raise ValueError('Require all three previously observed anchor failures')
    previous.fresh_output(output, cases)
    inputs = {str(p.resolve()): policy.admission.history.sha(p) for p in (admitted, Path(__file__), Path(policy.__file__))}
    observations = []
    for case in cases:
        index = policy.baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observations.append(dict(task_id=case['task_id'], **policy.retrieval.retrieve(index, case['description'])))
    policy.write_json(output / 'observations.json', observations)
    inputs[str(output / 'observations.json')] = policy.admission.history.sha(output / 'observations.json')
    report = {'complete': False, 'runs': [], 'protocol': {'name': 'exact-anchor-recovery-v1',
        'scope': 'three selected known failures; not new heldout/generalization evidence',
        'config': policy.repair.config().to_dict(), 'max_calls': 2, 'token_budget': 15000,
        'intervention': 'one resubmission only after rejected exact-match transaction; no behavior-test feedback',
        'unique_match_version_checks': 'unchanged', 'no_private_grader_input': True, 'frozen_inputs': inputs}}

    def frozen():
        policy.repair.check_identity(policy.repair.config())
        if any(policy.admission.history.sha(Path(p)) != h for p, h in inputs.items()):
            raise ValueError('Frozen adapter/input changed')
        for case in cases:
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source/tests changed')

    def save():
        report['summary'] = {p: policy.baseline.summarize([r for r in report['runs'] if r['policy'] == p])
                             for p in ('single', 'anchor-recovery')}
        policy.write_json(output / 'experiment.json', report)

    frozen()
    save()
    for case, observed in zip(cases, observations):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        path = root / 'job.json'
        policy.write_json(path, {**{k: case[k] for k in ('description', 'allowed_files')},
                               'workspace': str(workspace), 'evidence': observed['evidence']})
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.exact_anchor_recovery_v1', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = previous.load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
            'status': 'agent_error', 'metrics': None}
        for strategy, source in [('single', root / 'initial-workspace'), ('anchor-recovery', workspace)]:
            grade = root / ('grade-' + strategy)
            grade.mkdir()
            verified = policy.baseline.verify(case, source if source.exists() else workspace, grade)
            chosen = dict(result)
            if strategy == 'single':
                chosen.update(status=result.get('initial', {}).get('status', result['status']), metrics=result.get('initial_metrics'))
            accepted = chosen['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'split': 'diagnostic', 'repo': case['repo'],
                                  'policy': strategy, 'worker': chosen, 'verification': verified, 'accepted': accepted,
                                  'status': 'passed' if accepted else 'failed_verification' if chosen['status'] == 'completed'
                                  else chosen['status'], 'process': process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'], flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 6
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
        parser.error('Use --worker or --admission/--output')
