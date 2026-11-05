"""Serial, resumable Mini-50 evaluation with separate Agent and grading processes."""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from evals.swebench_images import ImageTransfer, release, space
from evals.swebench_mini import ROOT, load_entry, prepare, select, sha, write

MINI_REVISION = 'b316c349947c29963fce3f4a65967c9807a4b673'
OFFICIAL_REVISION = '78f471bf655a3137b2e8a75af1501690ec009ec3'
SOURCE_FILES = ('evals/swebench_agent.py', 'evals/swebench_mini.py', 'evals/swebench_images.py',
                'evals/swebench_batch.py', 'deploy/langfuse/swebench_batch.py',
                'evals/runtime.py', 'evals/schema.py', 'evals/runner.py', 'repairflow/issue_tools.py',
                'repairflow/issue_providers.py', 'repairflow/telemetry.py', 'deploy/langfuse/swebench_agent.py')


def save(path, value):
    pending = path.with_suffix('.pending')
    write(pending, value)
    pending.replace(path)


def environment(phase, output):
    env = dict(os.environ)
    deps = (['langfuse-deps', 'workflow-deps'] if phase in {'agent', 'publish'}
            else ['swebench-v5-deps', 'swebench-deps'])
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT / '.tmp' / name) for name in deps] + [str(ROOT)]),
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHON_DOTENV_DISABLED='1',
               TEMP=str(ROOT / '.tmp'), TMP=str(ROOT / '.tmp'),
               CORECODER_HOME=str(output / 'agent-state'),
               HF_HOME=str(ROOT / '.tmp/swebench-cache/hf'), XDG_CACHE_HOME=str(ROOT / '.tmp/swebench-cache'),
               NO_PROXY='127.0.0.1,localhost,::1')
    # Explicit provider; never pass paid API keys or inherited credentials to the Agent.
    for key in list(env):
        if key.endswith('_API_KEY') or key in {'OPENAI_BASE_URL', 'DEEPSEEK_BASE_URL'}:
            env.pop(key)
    env['CORECODER_LANGFUSE_ENABLED'] = '1' if phase in {'agent', 'publish'} else '0'
    if phase in {'agent', 'publish'}:
        env['CORECODER_LANGFUSE_ENV_FILE'] = str(ROOT / '.tmp/langfuse-local/.env')
    return env


def child(module, args, phase, folder, timeout):
    with (folder / (phase + '.log')).open('ab') as stream:
        result = subprocess.run([sys.executable, '-B', '-m', module, *map(str, args)], cwd=ROOT,
                                env=environment(phase, folder), stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(phase + ' process failed; inspect its local log')


def aggregate(ids, tasks):
    graded = [tasks[key] for key in ids if tasks.get(key, {}).get('status') == 'graded']
    resolved = sum(row['resolved'] for row in graded)
    tokens = [row.get('total_tokens') for row in tasks.values() if row.get('agent_completed')]
    return {'scheduled': len(ids), 'terminal_tasks': sum(row.get('status') in
            {'graded', 'infra_error', 'interrupted_agent'} for row in tasks.values()),
            'graded': len(graded), 'resolved': resolved, 'unresolved_graded': len(graded) - resolved,
            'resolved_over_scheduled': resolved / len(ids),
            'resolved_over_graded': resolved / len(graded) if graded else None,
            'infra_errors': sum(row.get('status') == 'infra_error' for row in tasks.values()),
            'agent_stop_reasons': dict(Counter(row['agent_status'] for row in tasks.values()
                                               if row.get('agent_status'))),
            'actual_tokens_known_sum': sum(value for value in tokens if value is not None),
            'usage_unknown_tasks': sum(value is None for value in tokens),
            'fresh_model_calls': sum(row.get('fresh_model_calls', 0) for row in tasks.values())}


def initialize(output):
    import pyarrow.parquet as pq

    mini_path = ROOT / '.tmp/swebench-mini-setup-20261030/mini.parquet'
    official_path = ROOT / '.tmp/swebench-mini-setup-20261030/official-0.parquet'
    frozen = json.loads((ROOT / '.tmp/swebench-mini-entry-20261030/manifest.json').read_text(encoding='utf-8'))
    if sha(mini_path) != frozen['mini_parquet_sha256'] or sha(official_path) != frozen['official_parquet_sha256']:
        raise ValueError('Frozen source parquet changed')
    mini, official = (pq.read_table(path).to_pylist() for path in (mini_path, official_path))
    ids = sorted(row['instance_id'] for row in mini)
    for key in ids:
        select(mini, official, key)
    output.mkdir(parents=True, exist_ok=False)
    for key in ids:
        prepare(mini_path, official_path, MINI_REVISION, OFFICIAL_REVISION, output / 'entries' / key, key)
    protocol = {'schema_version': 'swebench-mini-batch-v1', 'instance_ids': ids,
                'mini_revision': MINI_REVISION, 'official_revision': OFFICIAL_REVISION,
                'mini_parquet_sha256': sha(mini_path), 'official_parquet_sha256': sha(official_path),
                'repo_counts': dict(Counter(row['repo'] for row in mini)),
                'model': 'qwen3.5:27b', 'thinking': False, 'max_steps': 20, 'token_budget': 30000,
                'max_edits': 6, 'max_output_tokens': 2048, 'context_tokens': 16000, 'deadline_seconds': 1200,
                'serial': True, 'paid_api_calls': False, 'automatic_model_retry': False,
                'source_files': {name: sha(ROOT / name) for name in SOURCE_FILES},
                'entry_manifests': {key: sha(output / 'entries' / key / 'manifest.json') for key in ids}}
    write(output / 'protocol.json', protocol)
    return protocol


def run(output, resume=False):
    protocol = (json.loads((output / 'protocol.json').read_text(encoding='utf-8')) if resume else initialize(output))
    if any(sha(ROOT / name) != digest for name, digest in protocol['source_files'].items()):
        raise ValueError('Batch code changed; cannot mix protocols on resume')
    for key, digest in protocol['entry_manifests'].items():
        if sha(output / 'entries' / key / 'manifest.json') != digest:
            raise ValueError('Batch task changed')
    # One process owns a batch. OS releases this byte lock on termination.
    lock = (output / 'batch.lock').open('a+b')
    lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        return execute(output, protocol, resume)
    finally:
        lock.close()


def execute(output, protocol, resume):
    import urllib.request

    model = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10))
    digest = next(row['digest'] for row in model['models'] if row['name'] == protocol['model'])
    model_file = output / 'model-before.json'
    if model_file.exists():
        if json.loads(model_file.read_text(encoding='utf-8'))['digest'] != digest:
            raise ValueError('Model digest changed')
    else:
        write(model_file, {'model': protocol['model'], 'digest': digest, 'recorded_before_inference': True})
    report_file = output / 'report.json'
    report = (json.loads(report_file.read_text(encoding='utf-8')) if resume and report_file.exists()
              else {'status': 'running', 'protocol_sha256': sha(output / 'protocol.json'), 'tasks': {}})
    ids, tasks = protocol['instance_ids'], report['tasks']
    infrastructure_streak = 0
    for number, key in enumerate(ids, 1):
        if tasks.get(key, {}).get('status') in {'graded', 'infra_error', 'interrupted_agent'}:
            continue
        space(output)
        entry, folder = output / 'entries' / key, output / 'tasks' / key
        folder.mkdir(parents=True, exist_ok=True)
        state = tasks.setdefault(key, {'status': 'preparing'})
        report.update(status='running', current_task=key, current_index=number)
        report['summary'] = aggregate(ids, tasks)
        save(report_file, report)
        print(f'[{number}/50] {key}: preparing', flush=True)
        receipt = None
        phase = 'image'
        try:
            _manifest, row = load_entry(entry)
            transfer = ImageTransfer(folder / 'image-cache')
            receipt = transfer.load(row['image'])
            write(folder / 'image.json', receipt)
            image_id = receipt['image_id']
            phase = 'controls'
            state['phase'] = phase
            save(report_file, report)
            controls = folder / 'controls'
            if not (controls / 'report.json').exists():
                child('evals.swebench_mini', ['run', '--entry', entry, '--image-id', image_id,
                      '--output', controls], phase, folder, 1500)
            controls_report = json.loads((controls / 'report.json').read_text(encoding='utf-8'))
            if controls_report['status'] != 'passed' or controls_report['image_id'] != image_id:
                raise ValueError('Harness admission failed; do not count as model failure')
            phase = 'agent'
            attempt = folder / 'agent'
            if attempt.exists() and not (attempt / 'report.json').exists():
                state.update(status='interrupted_agent', phase=phase)
                continue  # Never silently rerun a partially executed inference.
            if not attempt.exists():
                state.update(status='running_agent', phase=phase)
                save(report_file, report)
                child('evals.swebench_agent', ['--entry', entry, '--image-id', image_id, '--output', attempt,
                      '--model', protocol['model']], phase, folder, 1350)
            agent = json.loads((attempt / 'report.json').read_text(encoding='utf-8'))
            metrics = agent.get('metrics', {})
            counts = [metrics.get('prompt_tokens'), metrics.get('completion_tokens')]
            state.update(agent_completed=True, agent_status=agent['status'],
                         fresh_model_calls=agent['fresh_model_calls'],
                         total_tokens=sum(counts) if all(value is not None for value in counts) else None,
                         trace_id=agent.get('observability', {}).get('trace_id'))
            phase = 'grading'
            state['phase'] = phase
            save(report_file, report)
            grading = folder / 'grading'
            if not (grading / 'report.json').exists():
                child('evals.swebench_mini', ['grade-candidate', '--entry', entry, '--candidate', attempt / 'patch.diff',
                      '--image-id', image_id, '--output', grading], phase, folder, 750)
            grade = json.loads((grading / 'report.json').read_text(encoding='utf-8'))
            if grade['status'] != 'completed' or grade['candidate_sha256'] != sha(attempt / 'patch.diff'):
                raise ValueError('Independent grading incomplete or candidate changed')
            state.update(status='graded', resolved=grade['candidate']['resolved'],
                         FAIL_TO_PASS=grade['candidate']['FAIL_TO_PASS'], PASS_TO_PASS=grade['candidate']['PASS_TO_PASS'])
            infrastructure_streak = 0
            print(f'[{number}/50] {key}: resolved={state["resolved"]}, stop={state["agent_status"]}', flush=True)
        except Exception as exc:  # noqa: BLE001 - isolate one task, preserve the remaining denominator
            state.update(status='infra_error', phase=phase, error_type=type(exc).__name__)
            infrastructure_streak += 1
            print(f'[{number}/50] {key}: infra_error in {phase}: {type(exc).__name__}', flush=True)
        finally:
            if receipt:
                try:
                    release(receipt)
                    state['image_cleanup'] = 'released' if receipt['owned'] else 'preexisting_retained'
                except Exception as exc:  # noqa: BLE001 - no forced cleanup of shared resources
                    state['image_cleanup'] = type(exc).__name__
            report['summary'] = aggregate(ids, tasks)
            save(report_file, report)
        if infrastructure_streak >= 3:
            report['status'] = 'paused_infrastructure'
            save(report_file, report)
            return report
    report.update(status='completed' if all(row['status'] == 'graded' for row in tasks.values())
                  and len(tasks) == 50 else 'completed_with_infra_errors', completed_at=time.time())
    report['summary'] = aggregate(ids, tasks)
    save(report_file, report)
    child('deploy.langfuse.swebench_batch', ['--batch', output], 'publish', output, 300)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if (not output.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and output.drive.lower() != 'd:')
            or (output.exists() and not args.resume)):
        parser.error('Use a new D: project .tmp directory, or --resume a frozen batch')
    result = initialize(output) if args.prepare_only else run(output, args.resume)
    print(json.dumps(result['summary'] if 'summary' in result else
                     {'prepared_tasks': len(result['instance_ids'])}), flush=True)


if __name__ == '__main__':
    main()
