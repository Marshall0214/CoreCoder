"""Replay saved model answers with strict JSON-envelope parsing, no new inference."""
import argparse
import json
import shutil
from pathlib import Path

from docs.experiments import function_replace_compare_v1 as comparison
from docs.experiments import function_replace_worker_v2 as worker
from docs.experiments.tentative_feedback_audit_v1 import Replay
from evals.runtime import BudgetLLM, Events

ROOT = comparison.ROOT
HISTORY = ROOT/'.tmp/real-defects/function-replace-compare-v1'


def run(output):
    output = output.resolve()
    cases, grades = comparison.preparation.prepare(output)
    prior = json.loads((HISTORY/'experiment.json').read_text(encoding='utf-8'))
    if not prior['complete']:
        raise ValueError('Expected completed v1 comparison')
    for name, value in prior['protocol']['adapter_hashes'].items():
        if comparison.repair.audit.sha(ROOT/name) != value:
            raise ValueError('Frozen v1 inputs changed')
    by_task = {c['task_id']: (c, g) for c, g in zip(cases, grades)}
    output.mkdir(parents=True)
    paths = [Path(__file__), Path(worker.__file__), Path(worker.replacement.__file__),
             Path(worker.replacement.base.__file__), HISTORY/'experiment.json']
    hashes = {p.relative_to(ROOT).as_posix(): comparison.repair.audit.sha(p) for p in paths}
    report = {'protocol': 'function-replace-replay-v2', 'complete': False, 'new_model_calls': 0,
              'private_task_verifications': 0, 'adapter_hashes': hashes, 'runs': []}
    def save():
        (output/'replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    for row in prior['runs']:
        name, policy = row['task_id'], row['policy']
        case, grade = by_task[name]
        history = HISTORY/name/policy
        root = output/name/policy
        root.mkdir(parents=True)
        workspace = root/'workspace'
        shutil.copytree(case['before'], workspace)
        before = comparison.repair.snapshot(workspace)
        job = json.loads((history/'job.json').read_text(encoding='utf-8'))
        job['workspace'] = str(workspace.resolve())
        raw = Replay(history, row['worker'])
        events = Events(root/'trace.jsonl', policy)
        llm = BudgetLLM(raw, comparison.repair.config(), events)
        result = worker.run_candidate(llm, job, events)
        if len(raw.calls) != 2:
            raise ValueError('Expected identical two-request replay')
        verifier = comparison.second.verify if name.startswith('itsdangerous-') else comparison.repair.verify
        verified = verifier(grade['case'], grade['source_root'], grade['checks'], workspace, before,
                            case['allowed_files'], root, grade['python'], 15)
        report['private_task_verifications'] += 1
        accepted = result['status'] == 'completed' and verified['passed']
        report['runs'].append({'task_id': name, 'policy': policy, 'status': 'passed' if accepted else
                               'failed_verification' if result['status'] == 'completed' else result['status'],
                               'accepted': accepted, 'worker': result, 'verification': verified,
                               'replayed_usage': llm.metrics(), 'requests': raw.calls})
        save()
        print(f'{name} {policy}: {report["runs"][-1]["status"]}', flush=True)
    if any(comparison.repair.audit.sha(ROOT/name) != value for name, value in hashes.items()):
        raise ValueError('Replay inputs changed')
    report['complete'] = len(report['runs']) == 4
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
