"""Fresh single-task PPC acceptance; no historical candidate or private feedback."""
import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from integrations import harness2 as bridge
from integrations import harness2_batch as batch
from integrations.harness2_runtime import COMMIT, ROOT


def execute(output):
    output.mkdir(parents=True, exist_ok=False)
    case = next(row for row in bridge.read(batch.MANIFEST)['cases']
                if row['task_id'] == 'toolz-join-unmatched')
    source_files = {name: bridge.sha(ROOT / name) for name in batch.CODE}
    for name in source_files:
        target = output / 'implementation' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copyfile(__file__, output / 'controller.py')
    bridge.write(output / 'protocol.json', {
        'schema': 'indexed-fresh-ppc-acceptance-v1', 'case': case,
        'upstream_commit': COMMIT, 'model': 'qwen3.5:27b', 'thinking': False,
        'editor_evidence': 'indexed', 'candidate_policy': 'public-preserve-v1',
        'feedback_rounds': 20, 'editor_model_steps': 20,
        'token_budget': None, 'output_tokens': None,
        'reuse_old_candidates': False, 'cross_task_memory': False,
        'independent_grading': 'after PPC, adoption and reflection terminate',
        'source_files': source_files, 'controller_sha256': bridge.sha(Path(__file__)),
        'historical_batch_sha256': bridge.sha(batch.ROOT / '.tmp/harness2-vs-control-50-20261105/report.json'),
        'started_at': datetime.now(timezone.utc).isoformat()})
    report = {'status': 'preflight', 'task_id': case['task_id'], 'paid_api_calls': 0}
    bridge.write(output / 'report.json', report)
    started = time.monotonic()
    try:
        bridge.write(output / 'identity/job.json', {'kind': 'identity', 'case': case})
        bridge.child(output / 'identity/job.json', 60)
        bridge.write(output / 'admission/job.json', {'kind': 'admission', 'case': case})
        batch.run_child(output / 'admission/job.json', timeout=180)
        report.update(status='running_fresh_ppc', admission_passed=True)
        bridge.write(output / 'report.json', report)
        print('identity and Docker public admission passed; starting fresh PPC', flush=True)
        public = {'instance_id': case['task_id'], 'repo': case['repo'],
                  'base_commit': 'source-sha256:' + case['before_hash'],
                  'problem_statement': case['description']}
        job = {'kind': 'experiment', 'arm': 'harness2', 'source': case['before'],
               'source_hash': case['before_hash'], 'public_task': public,
               'public_checks': case['harness'], 'package': case['package'],
               'source_root': case['source_root'], 'feedback_rounds': 20,
               'candidate_policy': 'public-preserve-v1', 'editor_evidence': 'indexed'}
        bridge.write(output / 'experiment/job.json', job)
        batch.run_child(output / 'experiment/job.json', controller=True)
        result = bridge.read(output / 'experiment/result.json')
        report['result'] = result
        report['ppc_terminated_at'] = datetime.now(timezone.utc).isoformat()
        report['status'] = 'ppc_terminated'
        bridge.write(output / 'report.json', report)
        if result['status'] == 'agent_completed':
            print('PPC terminated; independent grading of delivered candidate', flush=True)
            bridge.write(output / 'post-termination/job.json', {'kind': 'grade', 'case': case,
                'rollouts': [{'label': 'final', 'folder': result['final_rollout']}]})
            bridge.child(output / 'post-termination/job.json', 180)
            report['grading'] = bridge.read(output / 'post-termination/grading.json')['final']
            report['status'] = 'completed'
        else:
            report.update(status='completed_with_ppc_error', error=result.get('error'))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, error=str(exc))
    finally:
        if (output / 'experiment/result.json').exists():
            report['result'] = bridge.read(output / 'experiment/result.json')
        report['seconds'] = round(time.monotonic() - started, 3)
        report['ended_at'] = datetime.now(timezone.utc).isoformat()
        report['implementation_unchanged'] = all(bridge.sha(ROOT / name) == sha for name, sha in source_files.items())
        bridge.write(output / 'report.json', report)
        print(json.dumps({key: report.get(key) for key in ('status', 'error', 'seconds', 'implementation_unchanged')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    execute(parser.parse_args().output.resolve())
