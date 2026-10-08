"""Expose original post-call execution order without references or hidden tests."""
import argparse
import ast
import copy
import json
import os
import shutil
import sys
import textwrap
from pathlib import Path

from docs.experiments import click_resource_repair_v2 as baseline
from evals.process import run_process
from evals.runner import digest, snapshot

previous = baseline.previous


def facts(code):
    tree = ast.parse(textwrap.dedent(code))
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    body = tree.body[0].body
    rows = []
    for i, statement in enumerate(body[:-1]):
        calls = []
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            calls.append(statement.value)
        elif isinstance(statement, ast.If):
            calls.extend(n.value for n in statement.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))
        for call in calls:
            if any(isinstance(n, ast.Return) for n in ast.walk(statement)):
                continue
            rows.append({'call': ast.unparse(call),
                         'original_following_statements': [ast.unparse(n) for n in body[i+1:]],
                         'observation': 'This call originally falls through to these statements; an inserted early return can bypass them.'})
    return rows


def enrich(evidence, max_chars=6000):
    rows = copy.deepcopy(evidence)
    chars = sum(len(r['content']) for r in rows)
    for row in rows:
        observations = facts(row['content']) if row.get('complete_symbol') else []
        if not observations:
            continue
        extra = len(json.dumps(observations, ensure_ascii=False))
        if chars + extra > max_chars:
            raise ValueError('Source plus execution observations exceeds evidence budget')
        row['original_execution_order'] = observations
        chars += extra
    return rows, chars


def run(prior, output):
    load = baseline.stack.comparison.replay.load
    report = load(prior / 'repair.json')
    certificate = load(prior / 'certificate.json')
    original_job = load(prior / 'live' / 'job.json')
    if not report['complete'] or not certificate['certified']:
        raise ValueError('Require completed v2 run with certified checks')
    admitted_path = next(Path(p) for p in certificate['input_hashes'] if p.endswith('expanded-admission-v2-final\\admission.json'))
    case = next(c for c in load(admitted_path)['cases'] if c['task_id'] == baseline.TASK)
    protected = [prior.resolve(), *(Path(case[k]).resolve() for k in ('before', 'after', 'checks'))]
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh output outside frozen inputs required')
    inputs = dict(certificate['input_hashes'])
    for p in (prior / 'repair.json', prior / 'certificate.json', prior / 'live' / 'job.json', Path(__file__)):
        inputs[str(p.resolve())] = previous.admission.history.sha(p)
    private_path = prior / 'grading-checks-v2'

    def unchanged():
        if any(previous.admission.history.sha(Path(p)) != h for p, h in inputs.items()):
            raise ValueError('Frozen input changed')
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Frozen source/checks changed')
        for name in ('harness', 'frozen_harness'):
            if digest(snapshot(Path(original_job[name]))) != original_job[name + '_hash']:
                raise ValueError('Certified public checks changed')
        if digest(snapshot(private_path)) != certificate['private_hash']:
            raise ValueError('Certified grading checks changed')

    unchanged()
    evidence, chars = enrich(original_job['evidence'])
    output.mkdir(parents=True)
    workspace = output / 'workspace'
    shutil.copytree(case['before'], workspace)
    job = dict(original_job, workspace=str(workspace), evidence=evidence)
    previous.write_json(output / 'job.json', job)
    process = run_process([sys.executable, '-B', '-m', 'docs.experiments.frozen_feedback_v1', '--worker', str(output / 'job.json')],
                          previous.ROOT, 600, output / 'worker.stdout.txt', output / 'worker.stderr.txt',
                          dict(os.environ, PYTHONPATH=str(previous.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
    if process['timed_out'] or process['returncode'] != 0:
        raise RuntimeError('Worker failed; inspect preserved logs')
    unchanged()
    result = load(output / 'worker-result.json')
    grade = output / 'verification'
    grade.mkdir()
    verified = previous.baseline.verify(dict(case, checks=str(private_path)), workspace, grade)
    accepted = result['status'] == 'completed' and result.get('published', False) and verified['passed']
    unchanged()
    data = {'complete': True, 'task_id': baseline.TASK, 'accepted': accepted, 'worker': result,
            'verification': verified, 'process': process, 'input_hashes': inputs,
            'source_and_observation_chars': chars,
            'protocol': {'config': previous.repair.config().to_dict(), 'model_digest': previous.repair.MODEL_DIGEST,
                         'change': 'First-request source evidence includes original AST fallthrough observations',
                         'feedback': 'Same v2 public checks; refreshed evidence uses existing policy without new annotations',
                         'limits': 'Known single-case sequential experiment, not shared-answer pairing or blind evidence; no default integration'}}
    previous.write_json(output / 'repair.json', data)
    print(json.dumps({'accepted': accepted, 'metrics': result.get('metrics'), 'source_chars': chars}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.prior.resolve(), args.output)
