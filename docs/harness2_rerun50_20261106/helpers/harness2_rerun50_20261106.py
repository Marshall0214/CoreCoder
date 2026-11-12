"""Fresh Harness2 fifty-task rerun against a verified frozen historical control."""
import argparse
import ast
import copy
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from integrations import harness2 as bridge
from integrations import harness2_batch as batch
from integrations.harness2_runtime import ROOT

OLD = ROOT / '.tmp/harness2-vs-control-50-20261105'
OUTPUT = ROOT / '.tmp/harness2-v2-50-20261106'
TERMINAL = {'graded', 'error', 'interrupted'}


def now():
    return datetime.now(timezone.utc).isoformat()


def ast_part(text, name, parent=None):
    nodes = ast.parse(text).body
    if parent:
        nodes = next(node for node in nodes if getattr(node, 'name', None) == parent).body
    return ast.dump(next(node for node in nodes if getattr(node, 'name', None) == name), include_attributes=False)


def prepare():
    from evals.runner import digest, snapshot

    old_protocol = bridge.read(OLD / 'protocol.json')
    old_report = bridge.read(OLD / 'report.json')
    cases = bridge.read(batch.MANIFEST)['cases']
    assert len(cases) == 50 and cases == old_protocol['cases']
    assert bridge.sha(batch.MANIFEST) == old_protocol['manifest_sha256']
    assert set(old_report['tasks']['no_harness']) == {case['task_id'] for case in cases}
    assert all(row['status'] == 'graded' for row in old_report['tasks']['no_harness'].values())
    assert sum(row['resolved'] is True for row in old_report['tasks']['no_harness'].values()) == 24
    batch.initialize(OUTPUT, 'public-preserve-v1', 'indexed')
    bridge.write(OUTPUT / 'identity/job.json', {'kind': 'identity', 'case': cases[0]})
    bridge.child(OUTPUT / 'identity/job.json', 60)
    assert bridge.read(OUTPUT / 'identity/identity.json') == bridge.read(OLD / 'identity/identity.json')
    historical = OUTPUT / 'historical'
    historical.mkdir()
    for name in ('protocol.json', 'report.json'):
        shutil.copyfile(OLD / name, historical / name)
    changed = {name for name, value in old_protocol['source_files'].items() if bridge.sha(ROOT / name) != value}
    assert changed <= {'integrations/harness2.py', 'integrations/harness2_batch.py', 'integrations/harness2_evidence.py'}
    archived = ROOT / 'docs/harness2_batch_audit_20261106/original-implementation/integrations/harness2.py.txt'
    old_text, new_text = archived.read_text(encoding='utf-8'), (ROOT / 'integrations/harness2.py').read_text(encoding='utf-8')
    assert ast_part(old_text, 'Adapter', 'classes') == ast_part(new_text, 'Adapter', 'classes')
    for name in ('child',):
        assert ast_part(old_text, name) == ast_part(new_text, name)
    before_worker = ast.parse(old_text)
    after_worker = ast.parse(new_text)
    for tree in (before_worker, after_worker):
        function = next(node for node in tree.body if getattr(node, 'name', None) == 'worker')
        branch = next(node for node in function.body if isinstance(node, ast.If) and
                      ast.unparse(node.test) == "kind == 'rollout'")
        tree.control_branch = ast.dump(ast.Module(body=branch.body, type_ignores=[]), include_attributes=False)
    assert before_worker.control_branch == after_worker.control_branch
    inputs, reused = {}, {}
    for case in cases:
        key = case['task_id']
        for name in ('before', 'after', 'checks', 'harness'):
            assert digest(snapshot(Path(case[name]))) == case[name + '_hash'], (key, name)
        state = copy.deepcopy(old_report['tasks']['no_harness'][key])
        old_folder = Path(state['result']['final_rollout'])
        candidate = bridge.read(old_folder / 'feedback/report.json')
        assert digest(snapshot(old_folder / 'feedback/workspace')) == candidate['final_candidate_hash']
        grading = OLD / 'arms/no_harness' / key / 'post-termination/grading.json'
        assert bridge.read(grading)['final'] == state['grade'] == bridge.read(old_folder / 'grading/report.json')
        assert state['resolved'] is state['grade']['resolved']
        admission = OLD / 'admission' / key / 'result.json'
        assert bridge.read(admission) == old_report['admission'][key] and old_report['admission'][key]['passed']
        for name, source in [('grading.json', grading), ('admission.json', admission),
                             ('public.json', old_folder / 'public.json')]:
            target = historical / key / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        state['historical_usage'] = copy.deepcopy(state['usage'])
        state['usage'] = {**state['usage'], 'fresh_model_calls': 0,
                          'historical_model_calls': state['usage'].get('fresh_model_calls'),
                          'phases': [], 'measurement_source': 'frozen historical control'}
        state['provenance'] = 'reused historical control; no fresh inference or grading'
        reused[key] = state
        inputs[key] = {'candidate_hash': candidate['final_candidate_hash'], 'grading_sha256': bridge.sha(grading),
                       'admission_sha256': bridge.sha(admission), 'inputs_verified': True}
    protocol = bridge.read(OUTPUT / 'protocol.json')
    protocol.update(name='harness2-v2-fifty-historical-control-v1', executed_arms=['harness2'],
        schedule='Only fifty new task-local PPC runs; historical no_harness reused',
        new_rollouts={'no_harness': 0, 'harness2': 200}, editor_model_steps=20,
        editor_final_requests_reserved=2, editor_seconds=300, prepared_at=now(),
        historical_control={'source': str(OLD), 'report_sha256': bridge.sha(OLD / 'report.json'),
            'protocol_sha256': bridge.sha(OLD / 'protocol.json'), 'resolved': 24, 'tasks': 50,
            'fresh_model_calls': 0, 'unknown_token_tasks': sum(row['usage']['tokens'] is None for row in reused.values()),
            'reuse_reason': 'Same tasks, model/sandbox, original Adapter/rollout and shared feedback/validation code',
            'not_a_concurrent_or_repeated_control': True},
        all_failures_in_denominator=True, automatic_failed_task_retry=False)
    for name in ('integrations/harness2_runtime.py', 'integrations/harness2-source.json',
                 '.tmp/harness2_rerun50_20261106.py'):
        protocol['source_files'][name] = bridge.sha(ROOT / name)
    for name in protocol['source_files']:
        target = OUTPUT / 'implementation' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    bridge.write(OUTPUT / 'protocol.json', protocol)
    report = bridge.read(OUTPUT / 'report.json')
    report.update(status='ready', tasks={'no_harness': reused, 'harness2': {}},
        admission=copy.deepcopy(old_report['admission']),
        admission_provenance='Reused frozen results after verifying all input hashes, test code and sandbox identity')
    bridge.write(OUTPUT / 'reuse-verification.json', {'passed': True, 'model_calls': 0, 'verified_tasks': 50,
        'adapter_and_rollout_ast_unchanged': True, 'changed_source_files': sorted(changed), 'inputs': inputs})
    bridge.write(OUTPUT / 'report.json', report)
    print(json.dumps({'status': 'ready', 'new_harness_tasks': 50, 'reused_control_resolved': 24,
                      'preparation_model_calls': 0}), flush=True)


def comparison(report, old_report):
    rows = report['tasks']['harness2']
    finished = {key: row for key, row in rows.items() if row['status'] in TERMINAL}
    complete = len(finished) == 50
    def resolved(row):
        return row['status'] == 'graded' and row.get('resolved') is True
    result = {'finished': len(finished), 'scheduled': 50, 'complete': complete,
        'resolved': sum(resolved(row) for row in finished.values()),
        'errors': sum(row['status'] in {'error', 'interrupted'} for row in finished.values()),
        'full_ppc_completed': sum(row.get('result', {}).get('optimization_complete') is True for row in finished.values()),
        'public_fallback_deliveries': [key for key, row in finished.items() if row.get('result', {}).get('adopted_label') not in (None, 'agg1')],
        'repair_rate': sum(resolved(row) for row in finished.values()) / 50 if complete else None,
        'control_reused': True, 'control_fresh_model_calls': 0}
    usages = [row.get('usage', {}) for row in finished.values()]
    for metric in ('tokens', 'fresh_model_calls'):
        measured = [row.get(metric) for row in usages]
        result[metric] = sum(measured) if complete and all(type(value) is int for value in measured) else None
        result['known_' + metric + '_minimum'] = sum(value for value in measured if type(value) is int)
    for name, arm in (('historical_control', 'no_harness'), ('historical_harness', 'harness2')):
        previous = old_report['tasks'][arm]
        result[name] = {'resolved_of_50': sum(resolved(row) for row in previous.values()),
            'new_successes': [key for key, row in finished.items() if resolved(row) and not resolved(previous[key])],
            'lost_successes': [key for key, row in finished.items() if not resolved(row) and resolved(previous[key])],
            'compared_finished_tasks': len(finished)}
    return result


def run():
    protocol = bridge.read(OUTPUT / 'protocol.json')
    old = bridge.read(OUTPUT / 'historical/report.json')
    assert bridge.sha(OUTPUT / 'historical/report.json') == protocol['historical_control']['report_sha256']
    with (OUTPUT / 'batch.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bridge.write(OUTPUT / 'controller.json', {'status': 'running', 'pid': os.getpid(), 'started_at': now(),
                                                'executed_arm': 'harness2', 'historical_control_reused': True})
        try:
            report = batch.execute(OUTPUT)
            data = comparison(report, old)
            data['source_files_unchanged'] = all(bridge.sha(ROOT / name) == value for name, value in protocol['source_files'].items())
            assert data['source_files_unchanged'], 'Execution implementation changed during the batch'
            bridge.write(OUTPUT / 'comparison.json', data)
            bridge.write(OUTPUT / 'controller.json', {'status': 'finished', 'pid': os.getpid(), 'ended_at': now(),
                'batch_status': report['status'], 'summary': data, 'exit_code': 0})
            print(json.dumps(data, ensure_ascii=False), flush=True)
        except Exception as exc:
            bridge.write(OUTPUT / 'controller.json', {'status': 'failed', 'pid': os.getpid(), 'ended_at': now(),
                'error_type': type(exc).__name__, 'error': str(exc), 'exit_code': 1})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    prepare() if args.prepare else run()
