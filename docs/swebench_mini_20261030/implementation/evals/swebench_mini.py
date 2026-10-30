"""Single-instance SWE-bench Mini harness controls; no Agent or model inference."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = 'MariusHobbhahn/swe-bench-verified-mini'
OFFICIAL = 'SWE-bench/SWE-bench_Verified'
HARNESS_VERSION = '5.0.2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def labels(row, key):
    value = row[key]
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError('Invalid test labels')
    if len(value) != len(set(value)):
        raise ValueError('Duplicate test labels')
    return value


def select(mini, official, instance_id=None):
    """Freeze the community subset; reject task drift when adding current official scripts."""
    ids = [row['instance_id'] for row in mini]
    if len(ids) != 50 or len(set(ids)) != 50:
        raise ValueError('Require exactly 50 unique Mini tasks')
    canonical = {row['instance_id']: row for row in official}
    if len(canonical) != len(official) or not set(ids) <= canonical.keys():
        raise ValueError('Mini tasks must belong to the official dataset')
    selected = instance_id or min(ids)
    if selected not in ids:
        raise ValueError('Selected task is outside Mini')
    original = next(row for row in mini if row['instance_id'] == selected)
    row = canonical[selected]
    for key in ('repo', 'base_commit', 'problem_statement', 'patch', 'test_patch', 'version'):
        if original[key] != row[key]:
            raise ValueError('Mini/official task drift: ' + key)
    for key in ('FAIL_TO_PASS', 'PASS_TO_PASS'):
        if not labels(row, key) or set(labels(original, key)) != set(labels(row, key)):
            raise ValueError('Mini/official test drift: ' + key)
    if not re.fullmatch(r'[0-9a-f]{40}', row['base_commit']):
        raise ValueError('Expected pinned base commit')
    expected_image = 'swebench/sweb.eval.x86_64.' + selected.replace('__', '_1776_') + ':latest'
    if row['image'] != expected_image:
        raise ValueError('Require the official single-instance x86_64 image')
    return row


def prepare(mini_path, official_path, mini_revision, official_revision, output, instance_id=None):
    for revision in (mini_revision, official_revision):
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Pin both dataset revisions')
    import pyarrow.parquet as pq

    mini, official = (pq.read_table(path).to_pylist() for path in (mini_path, official_path))
    row = select(mini, official, instance_id)
    output.mkdir(parents=True, exist_ok=False)
    # No gold patch, grading tests, labels, hints or oracle file list in Agent input.
    write(output / 'agent/input.json', {key: row[key] for key in
                                      ('instance_id', 'repo', 'base_commit', 'problem_statement')})
    write(output / 'grader/instance.json', row)
    manifest = {'schema_version': 'swebench-mini-controls-v1', 'dataset': DATASET, 'split': 'test',
                'mini_revision': mini_revision, 'mini_parquet_sha256': sha(mini_path),
                'official_dataset': OFFICIAL, 'official_revision': official_revision,
                'official_parquet_sha256': sha(official_path), 'harness_version': HARNESS_VERSION,
                'instance_ids': sorted(item['instance_id'] for item in mini), 'subset_count': len(mini),
                'selected_instance_id': row['instance_id'],
                'selection_rule': 'explicit ID' if instance_id else 'lexicographically first ID before execution',
                'agent_input_fields': ['instance_id', 'repo', 'base_commit', 'problem_statement'],
                'files': {name: sha(output / name) for name in ('agent/input.json', 'grader/instance.json')}}
    write(output / 'manifest.json', manifest)
    return manifest


def load_entry(entry):
    manifest = json.loads((entry / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['dataset'] != DATASET or manifest['harness_version'] != HARNESS_VERSION:
        raise ValueError('Unsupported control protocol')
    if set(manifest['files']) != {'agent/input.json', 'grader/instance.json'}:
        raise ValueError('Invalid entry files')
    if any(sha(entry / name) != digest for name, digest in manifest['files'].items()):
        raise ValueError('Prepared input changed')
    row = json.loads((entry / 'grader/instance.json').read_text(encoding='utf-8'))
    if row['instance_id'] != manifest['selected_instance_id']:
        raise ValueError('Task mismatch')
    return manifest, row


def summarize(report, row):
    result = report[row['instance_id']]
    if result.get('infra_failure') or 'tests_status' not in result:
        raise ValueError('No trustworthy parsed test result; not an Agent failure')
    summary = {'resolved': result['resolved']}
    for key in ('FAIL_TO_PASS', 'PASS_TO_PASS'):
        group = result['tests_status'][key]
        passed, failed, expected = group['success'], group['failure'], labels(row, key)
        if (len(passed) != len(set(passed)) or len(failed) != len(set(failed))
                or set(passed) & set(failed) or set(passed) | set(failed) != set(expected)):
            raise ValueError('Incomplete or inconsistent grading labels')
        summary[key] = {'passed': len(passed), 'failed': len(failed), 'total': len(expected)}
    all_passed = all(summary[key]['failed'] == 0 for key in ('FAIL_TO_PASS', 'PASS_TO_PASS'))
    if type(summary['resolved']) is not bool or summary['resolved'] != all_passed:
        raise ValueError('Inconsistent resolution flag')
    return summary


def docker(*args, timeout=30):
    return subprocess.run(['docker', *map(str, args)], capture_output=True, check=True,
                          timeout=timeout).stdout


def control(row, spec, mode, image_id, output, timeout):
    output.mkdir(parents=True, exist_ok=False)
    suffix = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:12]
    container = 'corecoder-swe-control-' + suffix
    started, created = time.monotonic(), False
    try:
        # No host mounts, daemon socket, host credentials or external network.
        # The official setup script needs a writable filesystem and root for locales.
        docker('create', '--name', container, '--label', 'corecoder.swebench-control=' + suffix,
               '--network', 'none', '--cpus', '2', '--memory', '4g', '--pids-limit', '256',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--log-opt', 'max-size=10m', '--log-opt', 'max-file=2',
               '--env', 'PIP_NO_INDEX=1', '--env', 'PIP_DISABLE_PIP_VERSION_CHECK=1',
               '--env', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', '/bin/sh', image_id, '-c', 'sleep infinity')
        created = True
        docker('start', container)
        initial_head = docker('exec', '-w', '/testbed', container, 'git', 'rev-parse', 'HEAD').decode().strip()
        # Published images can contain a setup commit. Normalize only this fresh,
        # mount-free container to the dataset revision before either control.
        docker('exec', '-w', '/testbed', container, 'git', 'checkout', '--detach', row['base_commit'])
        actual = docker('exec', '-w', '/testbed', container, 'git', 'rev-parse', 'HEAD').decode().strip()
        if actual != row['base_commit']:
            raise ValueError('Image does not contain the pinned base commit')
        docker('exec', '-w', '/testbed', container, 'git', 'diff', '--exit-code', 'HEAD', '--')
        patch = row['patch'] if mode == 'reference' else ''
        (output / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
        if patch:
            docker('cp', output / 'patch.diff', container + ':/candidate.diff')
            docker('exec', '-w', '/testbed', container, 'git', 'apply', '--check', '/candidate.diff')
            docker('exec', '-w', '/testbed', container, 'git', 'apply', '/candidate.diff')
        (output / 'eval.sh').write_text(spec.eval_script, encoding='utf-8', newline='\n')
        docker('cp', output / 'eval.sh', container + ':/eval.sh')
        process = subprocess.run(['docker', 'exec', container, '/bin/bash', '/eval.sh'],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        (output / 'test_output.txt').write_bytes(process.stdout)
        # Exit zero may only describe the script's final git checkout, not its tests.
        from swebench.harness.grading import get_eval_report

        prediction = {'instance_id': row['instance_id'], 'model_name_or_path': 'control-' + mode,
                      'model_patch': patch}
        report = get_eval_report(spec, prediction, str(output / 'test_output.txt'), include_tests_status=True)
        write(output / 'official-report.json', report)
        result = {'mode': mode, 'script_exit_code': process.returncode, 'seconds': round(time.monotonic() - started, 3),
                  'patch_source': 'dataset_reference' if patch else 'unchanged', 'base_commit_verified': actual,
                  'image_initial_head': initial_head,
                  'patch_sha256': sha(output / 'patch.diff'), 'fresh_model_calls': 0,
                  'is_agent_result': False, **summarize(report, row)}
        write(output / 'summary.json', result)
        return result
    finally:
        if created:
            docker('rm', '--force', container)


def run(entry, output, image_id, timeout=600):
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    import swebench
    from swebench.harness.utils import make_test_spec

    if swebench.__version__ != HARNESS_VERSION:
        raise ValueError('Use pinned official harness ' + HARNESS_VERSION)
    manifest, row = load_entry(entry)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise ValueError('Use an immutable local image ID')
    image = json.loads(docker('image', 'inspect', row['image']).decode())[0]
    if image['Id'] != image_id:
        raise ValueError('Task tag does not match pinned image ID')
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'incomplete', 'scope': 'Single-task harness admission, not Agent accuracy',
              'instance_id': row['instance_id'], 'dataset': DATASET, 'subset_count': 50,
              'evaluated_unique_tasks': 1, 'fresh_model_calls': 0, 'harness_version': HARNESS_VERSION,
              'mini_revision': manifest['mini_revision'], 'official_revision': manifest['official_revision'],
              'entry_manifest_sha256': sha(entry / 'manifest.json'), 'image_id': image_id,
              'image_layers': image['RootFS']['Layers'],
              'execution': 'Local restricted Docker orchestration; official eval script, parser and grader'}
    try:
        spec = make_test_spec(row)
        for mode in ('unchanged', 'reference'):
            print('Running harness control: ' + mode, flush=True)
            result[mode] = control(row, spec, mode, image_id, output / mode, timeout)
        unchanged, reference = result['unchanged'], result['reference']
        if (unchanged['resolved'] or unchanged['FAIL_TO_PASS']['failed'] == 0
                or unchanged['PASS_TO_PASS']['failed'] or not reference['resolved']):
            raise ValueError('Control pair failed admission')
        result['status'] = 'passed'
        return result
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        write(output / 'report.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--mini-parquet', type=Path, required=True)
    prepare_parser.add_argument('--official-parquet', type=Path, required=True)
    prepare_parser.add_argument('--mini-revision', required=True)
    prepare_parser.add_argument('--official-revision', required=True)
    prepare_parser.add_argument('--instance-id')
    run_parser = sub.add_parser('run')
    run_parser.add_argument('--entry', type=Path, required=True)
    run_parser.add_argument('--image-id', required=True)
    run_parser.add_argument('--timeout', type=int, default=600)
    for command_parser in (prepare_parser, run_parser):
        command_parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a new output directory within project .tmp on D:')
    if os.name == 'nt' and output.drive.lower() != 'd:':
        parser.error('Runtime data must stay on D:')
    if args.command == 'prepare':
        result = prepare(args.mini_parquet, args.official_parquet, args.mini_revision,
                         args.official_revision, output, args.instance_id)
        print(json.dumps({'status': 'prepared', 'instance_id': result['selected_instance_id'], 'subset_count': 50}))
    else:
        if not 1 <= args.timeout <= 1800:
            parser.error('Timeout must be from 1 to 1800 seconds')
        result = run(args.entry.resolve(), output, args.image_id, args.timeout)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
