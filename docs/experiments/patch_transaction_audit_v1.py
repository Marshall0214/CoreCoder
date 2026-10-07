"""Offline replay of frozen model patches through opt-in transaction validation."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from docs.experiments import patch_transaction_v1 as guard
from docs.experiments import repair_forwarding_worker_v1 as forwarding
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import salt_relations_audit_v1 as relations
from docs.experiments import thinking_calibration_cases_v1 as fixtures
from docs.experiments import thinking_calibration_v1 as calibration
from evals.symbol_context import apply_symbol_patch

ROOT = Path(__file__).resolve().parents[2]
HISTORY = ROOT / '.tmp/real-defects/salt-relations-feedback-v1'
CALIBRATION = ROOT / '.tmp/calibration/thinking-v1-live'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def whole_evidence(workspace, names):
    return [{'path': name, 'content': (workspace / name).read_text(encoding='utf-8'),
             'content_hash': sha(workspace / name)} for name in names]


def audit(output):
    output = output.resolve()
    cases, grades = public.comparison.prepare(output)
    case, grade = next((c, g) for c, g in zip(cases, grades) if c['task_id'] == relations.TASK)
    history = json.loads((HISTORY / 'experiment.json').read_text(encoding='utf-8'))
    live = json.loads((CALIBRATION / 'experiment.json').read_text(encoding='utf-8'))
    if not history['complete'] or not live['complete']:
        raise ValueError('Historical inputs must be complete')
    for record in (history, live):
        if any(sha(ROOT / name) != value for name, value in record['protocol']['adapter_hashes'].items()):
            raise ValueError('Historical implementation hash mismatch')
    frozen = {}
    def freeze(path):
        frozen[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (HISTORY / 'experiment.json', CALIBRATION / 'experiment.json', relations.CHECK,
                 Path(guard.__file__), Path(__file__), Path(forwarding.__file__), Path(calibration.__file__)):
        freeze(path)
    source_hash = public.repair.digest(public.repair.snapshot(case['before']))
    if source_hash != history['protocol']['source_hashes'][relations.TASK]:
        raise ValueError('Historical source hash mismatch')
    output.mkdir(parents=True, exist_ok=False)
    imports = [{'module': 'itsdangerous', 'root': 'src', 'path': 'src/itsdangerous/__init__.py'}]
    report = {'protocol': 'patch-transaction-audit-v1', 'model_calls': 0, 'complete': False,
              'historical': [], 'positives': [], 'source_hash': source_hash}
    harness = output / 'harness'
    harness.mkdir()
    (harness / 'test_admission.py').write_bytes(relations.CHECK.read_bytes())
    harness_hash = public.repair.digest(public.repair.snapshot(harness))
    for row in history['runs']:
        branch = HISTORY / f"repeat-{row['repeat']:02d}" / relations.TASK / row['policy']
        job = json.loads((branch / 'job.json').read_text(encoding='utf-8'))
        for name in ('job.json', 'response.txt', 'feedback-response.txt'):
            freeze(branch / name)
        root = output / f"historical-{row['repeat']}-{row['policy']}"
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        # Reconstruct the exact pre-feedback state, not a hand-edited failed patch.
        apply_symbol_patch((branch / 'response.txt').read_text(encoding='utf-8'), workspace,
                           case['allowed_files'], job['evidence'])
        packed = forwarding.forwarding_context(workspace, case['allowed_files'], job['evidence'], case['description'])
        result = guard.transact((branch / 'feedback-response.txt').read_text(encoding='utf-8'), workspace,
                               case['allowed_files'], packed['evidence'], root / 'transaction', grade['python'], imports)
        checked = None
        if result['accepted']:
            checked, _ = public.check_public(workspace, harness, harness_hash, root / 'public-check', grade['python'], relations.TASK)
        report['historical'].append({'repeat': row['repeat'], 'policy': row['policy'],
                                     'transaction': result, 'public_check': checked})
    # Human correct real patch: use the already certified public witness.
    root = output / 'positive-real'
    workspace, witness = root / 'workspace', root / 'witness'
    shutil.copytree(case['before'], workspace)
    shutil.copytree(case['before'], witness)
    public.apply_witness(case, witness)
    names = [name for name in case['allowed_files'] if (workspace / name).read_bytes() != (witness / name).read_bytes()]
    evidence = whole_evidence(workspace, names)
    patch = json.dumps({'edits': [{'file': r['path'], 'old': r['content'],
                                  'new': (witness / r['path']).read_text(encoding='utf-8')} for r in evidence]})
    result = guard.transact(patch, workspace, names, evidence, root / 'transaction', grade['python'], imports)
    checked, _ = public.check_public(workspace, harness, harness_hash, root / 'public-check', grade['python'], relations.TASK)
    report['positives'].append({'task_id': relations.TASK, 'kind': 'human-certified', 'transaction': result,
                                'behavior_passed': checked['passed']})
    # Eight successful synthetic model patches, preserved separately from real defects.
    for row in live['runs']:
        task = next(c for c in fixtures.CASES if c['id'] == row['task_id'])
        mode = row['mode']
        branch = CALIBRATION / f"repeat-{row['repeat']:02d}" / task['id'] / mode
        freeze(branch / 'response.txt')
        root = output / f"positive-{task['id']}-{mode}"
        workspace = root / 'workspace'
        workspace.mkdir(parents=True)
        (workspace / 'app.py').write_bytes(task['source'].encode())
        result = guard.transact((branch / 'response.txt').read_text(encoding='utf-8'), workspace,
                               ['app.py'], whole_evidence(workspace, ['app.py']), root / 'transaction', sys.executable,
                               [{'module': 'app', 'root': '.', 'path': 'app.py'}])
        check = root / 'checks.py'
        check.write_bytes(task['checks'].encode())
        checked = calibration.verify(workspace, check, root / 'verification', task['source'])
        report['positives'].append({'task_id': task['id'], 'kind': 'synthetic-model', 'mode': mode,
                                    'transaction': result, 'behavior_passed': checked['passed']})
    if (public.repair.digest(public.repair.snapshot(case['before'])) != source_hash
            or any(sha(ROOT / name) != value for name, value in frozen.items())):
        raise ValueError('Frozen replay inputs changed')
    report['input_hashes'] = frozen
    rejected = [r for r in report['historical'] if not r['transaction']['accepted']]
    admitted = [r for r in report['historical'] if r['transaction']['accepted']]
    report['summary'] = {'historical_rejected': len(rejected), 'historical_total': len(report['historical']),
                         'accepted_but_behavior_failed': sum(not r['public_check']['passed'] for r in admitted),
                         'positive_accepted': sum(r['transaction']['accepted'] for r in report['positives']),
                         'positive_total': len(report['positives'])}
    report['complete'] = (len(report['historical']) == 6 and len(report['positives']) == 9
                          and all(r['transaction']['original_unchanged'] for r in rejected)
                          and all(r['transaction']['accepted'] and r['behavior_passed'] for r in report['positives']))
    (output / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']))
    if not report['complete']:
        raise ValueError('Replay certification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output)
