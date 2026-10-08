"""Replay recorded answers through the new guarded repair workflow, without inference."""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from corecoder.llm import LLMResponse
from docs.experiments import frozen_feedback_v1 as workflow
from evals.runner import digest, implementation_metadata, snapshot
from evals.runtime import Events

previous = workflow.previous


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def answer_path(root, stage, status):
    number = '01' if stage == 'initial' else '02'
    for path in (root / (stage + '-response.txt'), root / ('provider-call-' + number) / 'response.txt'):
        if path.exists():
            return path
    if status in {'budget_exceeded', 'output_truncated', 'unexpected_thinking',
                  'empty_final_answer', 'model_identity_mismatch', 'unexpected_finish_reason'}:
        return None
    raise ValueError('Missing recorded ' + stage + ' response')


class RecordedAnswers:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = 0
        self.missing = False

    def chat(self, messages, tools=None):
        self.requests += 1
        if not self.answers:
            self.missing = True
            raise ValueError('No recorded answer available; no new inference allowed')
        content, status = self.answers.pop(0)
        if status == 'budget_exceeded':
            raise previous.baseline.BudgetExceeded('Recorded budget stop')
        if status in {'output_truncated', 'unexpected_thinking', 'empty_final_answer',
                      'model_identity_mismatch', 'unexpected_finish_reason'}:
            raise previous.baseline.InvalidCompletion(status)
        return LLMResponse(content=content, tool_calls=[], prompt_tokens=0, completion_tokens=0)

    def metrics(self):
        return {'llm_calls': 0, 'budget_accounted_tokens': 0,
                'replay_requests': self.requests, 'missing_recorded_answer': self.missing}


def prepare(audit, admitted, development, heldout, certificates):
    audited, admitted_data = load(audit), load(admitted)
    if (not audited['complete'] or len(audited['cases']) != 50
            or len({c['task_id'] for c in audited['cases']}) != 50 or not admitted_data['complete']):
        raise ValueError('Require complete frozen audit and admission')
    expected = audited['protocol']['input_hashes']
    for path in (admitted, development, heldout, *certificates):
        if expected.get(str(path.resolve())) != previous.admission.history.sha(path):
            raise ValueError('Input differs from certified audit')
    if any(previous.admission.history.sha(Path(p)) != value for p, value in expected.items()):
        raise ValueError('Certified audit input changed')
    cases = {c['task_id']: c for c in admitted_data['cases']}
    certs = {c['task_id']: c for path in certificates for c in load(path)['cases']}
    histories = {split: load(path) for split, path in [('development', development), ('heldout', heldout)]}
    paths = {'development': development, 'heldout': heldout}
    plan = []
    for audited_case in audited['cases']:
        if not audited_case['certified']:
            continue
        task = audited_case['task_id']
        case, cert = cases[task], certs[task]
        if case['split'] != audited_case['original_split']:
            raise ValueError('Task split changed')
        historical = paths[case['split']].parent / task
        job = load(historical / 'job.json')
        if (job['description'] != case['description'] or job['allowed_files'] != case['allowed_files']
                or digest(snapshot(Path(cert['harness']))) != cert['harness_hash']
                or digest(snapshot(Path(audited_case['harness']))) != audited_case['harness_hash']):
            raise ValueError('Certified task/harness differs')
        for field in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[field]))) != case[field + '_hash']:
                raise ValueError('Frozen source or grading checks changed')
        old = next(r for r in histories[case['split']]['runs']
                   if r['task_id'] == task and r['policy'] == 'public-feedback')
        old_worker = old['worker']
        answers = [answer_path(historical, 'initial', old_worker['initial']['status'])]
        if old_worker.get('feedback_attempts'):
            answers.append(answer_path(historical, 'feedback', old_worker['correction']['status']))
        plan.append({'case': case, 'certificate': cert, 'guard': audited_case,
                     'evidence': job['evidence'], 'historical': old, 'answers': answers})
    if len(plan) != 44:
        raise ValueError('Require the fixed 44 certified tasks')
    return plan, audited


def run(audit, admitted, development, heldout, certificates, output):
    plan, audited = prepare(audit, admitted, development, heldout, certificates)
    protected = [Path(row['case'][key]).resolve() for row in plan for key in ('before', 'after', 'checks')]
    protected += [p.parent.resolve() for p in (audit, development, heldout, *certificates)]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh output outside frozen inputs required')
    output.mkdir(parents=True)
    inputs = [audit, admitted, development, heldout, *certificates, Path(__file__), Path(workflow.__file__)]
    inputs += [p for row in plan for p in row['answers'] if p is not None]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in inputs}
    report = {'complete': False, 'runs': [], 'protocol': {
        'name': 'frozen-feedback-replay-v1', 'model_calls': 0, 'engine_hash': implementation_metadata()['source_hash'],
        'tasks': 44, 'excluded': audited['summary']['excluded'], 'input_hashes': hashes,
        'selection_uses_private_grader': False,
        'limits': 'Historical answers replayed under new prompts; not new inference or repair-rate evidence',
        'publication': 'owned task-local copies only; no default Agent/API integration'}}

    def save():
        rows = report['runs']
        report['summary'] = {'tasks': len(rows), 'published': sum(r['worker']['published'] for r in rows),
                             'verified': sum(r['accepted'] for r in rows),
                             'restored_original': sum(r['worker']['original_restored'] for r in rows),
                             'historical_scored_success': sum(r['historical_accepted'] for r in rows),
                             'rejected_historical_success': [r['task_id'] for r in rows if r['historical_accepted'] and not r['accepted']],
                             'statuses': dict(Counter(r['worker']['status'] for r in rows)),
                             'missing_recorded_answers': [r['task_id'] for r in rows if r['worker']['metrics']['missing_recorded_answer']],
                             'new_model_calls': 0}
        previous.write_json(output / 'replay.json', report)

    for item in plan:
        if any(previous.admission.history.sha(Path(p)) != value for p, value in hashes.items()):
            raise ValueError('Frozen replay input changed')
        case, cert, guard = item['case'], item['certificate'], item['guard']
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root')}
        job.update(workspace=str(workspace), evidence=item['evidence'], original_hash=case['before_hash'],
                   description_hash=cert['description_hash'], harness=cert['harness'], harness_hash=cert['harness_hash'],
                   frozen_harness=guard['harness'], frozen_harness_hash=guard['harness_hash'])
        previous.write_json(root / 'job.json', job)
        old_worker = item['historical']['worker']
        statuses = [old_worker['initial']['status'], old_worker.get('correction', {}).get('status', 'completed')]
        llm = RecordedAnswers([(p.read_text(encoding='utf-8') if p else '', statuses[i])
                               for i, p in enumerate(item['answers'])])
        result = workflow.run_candidate(llm, job, Events(root / 'trace.jsonl', case['task_id']))
        expected_initial = next(r['candidate_hash'] for r in guard['replays'] if r['policy'] == 'single')
        if digest(snapshot(root / 'initial-workspace')) != expected_initial:
            raise ValueError('Recorded initial answer did not reproduce historical source')
        previous.write_json(root / 'worker-result.json', result)
        grade = root / 'verification'
        grade.mkdir()
        verified = previous.baseline.verify(case, workspace, grade)
        accepted = result['status'] == 'completed' and result['published'] and verified['passed']
        if not result['published'] and not result['original_restored']:
            raise ValueError('Rejected candidate left modified source')
        report['runs'].append({'task_id': case['task_id'], 'original_split': case['split'],
                               'worker': result, 'verification': verified, 'accepted': accepted,
                               'historical_accepted': item['historical']['accepted']})
        save()
        print(case['task_id'], result['status'], 'published=', result['published'], flush=True)
    if any(previous.admission.history.sha(Path(p)) != value for p, value in hashes.items()):
        raise ValueError('Frozen replay input changed')
    report['complete'] = len(report['runs']) == 44
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--heldout', type=Path, required=True)
    parser.add_argument('--certificates', type=Path, nargs=2, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.audit.resolve(), args.admission.resolve(), args.development.resolve(), args.heldout.resolve(),
        [p.resolve() for p in args.certificates], args.output.resolve())
