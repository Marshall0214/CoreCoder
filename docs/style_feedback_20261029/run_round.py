"""Version the public preservation checks, admit offline, then run once locally."""
import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.runner import changes, snapshot
from repairflow.bundles import read, tree_hash, write
from repairflow.github_issue import NoRedirect, config
from repairflow.issue_repair import baseline_ready, execute, public_checks, trusted_task
from sandbox import runner

PREVIOUS = ROOT / '.tmp/github-issue-acceptance-20261019/click-3887-v2'
OLD_CONFIG = ROOT / 'configs/issue-tasks/click-3887.json'
CONFIG = ROOT / 'configs/issue-tasks/click-3887-style-v1.json'
CANDIDATE = ROOT / '.tmp/issue-compact-live-20261029/click-3887-qwen35-compact-001/workspace'
MODEL = 'qwen3.5:27b'
DIGEST = '7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen():
    for name, directory in [('compact-observations-20261029', 'compact_observations_20261029'),
                            ('compact-candidate-review-20261029', 'compact_candidate_review_20261029')]:
        manifest = read(ROOT / 'docs' / (name + '.json'))
        for relative, digest in manifest['files'].items():
            if sha(ROOT / 'docs' / directory / relative) != digest:
                raise ValueError('Frozen evidence changed: ' + relative)


def inputs():
    names = ('repairflow/issue_tools.py', 'repairflow/issue_agent.py', 'repairflow/issue_repair.py',
             'repairflow/issue_context.py', 'repairflow/issue_providers.py', 'evals/runtime.py', 'sandbox/runner.py')
    return {'previous_prepared': tree_hash(PREVIOUS), 'previous_configuration': sha(OLD_CONFIG),
            'previous_candidate': tree_hash(CANDIDATE), 'configuration': sha(CONFIG),
            'new_harness': tree_hash(CONFIG.parent / 'click-3887-style-v1'),
            'implementation': {name: sha(ROOT / name) for name in names}}


def local_get(endpoint):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open('http://127.0.0.1:11434/api/' + endpoint, timeout=10) as response:
        return json.load(response)


def prepare(root):
    if root.exists():
        raise ValueError('Require a fresh preparation output; never overwrite a prior attempt')
    frozen()
    previous, _ = trusted_task(PREVIOUS, OLD_CONFIG)
    original_plan = read(ROOT / 'docs/compact_observations_20261029/run-plan.json')
    if (previous['source_sha256'] != original_plan['source_sha256']
            or previous['harness_sha256'] != original_plan['harness_sha256']):
        raise ValueError('Previous task differs from frozen evidence')
    changed, patch = changes(snapshot(PREVIOUS / 'source'), snapshot(CANDIDATE))
    if changed != ['src/click/termui.py'] or patch != (
            ROOT / 'docs/compact_observations_20261029/live/patch.diff').read_text(encoding='utf-8'):
        raise ValueError('Prior candidate is not the frozen patch')
    settings = config(CONFIG, previous['issue_url'])
    policy = runner.preflight(settings['image'])
    if policy['image_id'] != previous['sandbox']['image_id']:
        raise ValueError('Pinned image changed')
    before = inputs()
    if before['implementation'] != original_plan['input_hashes']['implementation']:
        raise ValueError('Runtime implementation differs from method round one')
    root.mkdir(parents=True)
    write(root / 'intent.json', {'scope': 'Development-check expansion; not held-out or comparable frozen scoring',
          'major_change': 'Original target and controls plus six review-derived public preservation checks',
          'method_round': 2, 'new_task_runs_before': 1, 'planned_new_task_runs': 1, 'max_new_task_runs': 6,
          'hypothesis': 'Executable preservation counterexamples reject broad ANSI stripping and enable narrower repair.',
          'pass_criteria': 'Target 1/1 and preservation 9/9, net allowed source change, unchanged inputs; manual review remains.',
          'retake_policy': 'One local invocation from original source; preserve failure; no selected rerun.',
          'cloud_calls': 0, 'thinking': False, 'input_hashes': before})
    destination = root / 'prepared'
    destination.mkdir()
    shutil.copytree(PREVIOUS / 'source', destination / 'source')
    shutil.copytree(settings['harness'], destination / 'public')
    shutil.copyfile(PREVIOUS / 'issue.json', destination / 'issue.json')
    task = {key: value for key, value in previous.items() if key != 'task_sha256'}
    task.update(status='preparing', ready_for_repair=False, checks={}, config_sha256=settings['config_sha256'],
                harness_sha256=tree_hash(destination / 'public'), requested_urls=[],
                preparation_mode='local_snapshot_reuse_no_http', prepared_at=datetime.now(timezone.utc).isoformat(),
                derived_from={'task_sha256': previous['task_sha256'], 'config_sha256': previous['config_sha256'],
                              'harness_sha256': previous['harness_sha256'], 'fetched_at': previous['fetched_at']},
                evidence_scope='Expanded public DEVELOPMENT tests, derived after candidate review; no independent grader.')
    write(destination / 'task.json', task)
    try:
        admission = public_checks(destination / 'source', destination / 'public', task,
                                  destination / 'admission', policy, runner.owner(root))
        if (not baseline_ready(admission) or admission['Reproduce']['tests_run'] != 1
                or admission['Preserve']['tests_run'] != 9):
            raise ValueError('New base must fail exactly one target and pass nine preservation checks')
        challenge = public_checks(CANDIDATE, destination / 'public', task, root / 'old-candidate-checks',
                                  policy, runner.owner(root))
        if (not challenge['Reproduce']['passed'] or challenge['Preserve']['failures'] != 4
                or challenge['Preserve']['tests_run'] != 9 or challenge['Preserve']['errors']):
            raise ValueError('New checks must expose the four known regressions in the old candidate')
        task.update(status='ready_for_repair', ready_for_repair=True, checks=admission,
                    reproduction_failed_on_base=True, preservation_passed=True)
        write(destination / 'task.json', task)
        write(destination / 'report.json', {key: value for key, value in task.items() if key != 'description'})
        trusted_task(destination, CONFIG)
        write(root / 'preparation.json', {'status': 'ready_for_repair', 'fresh_model_calls': 0,
              'baseline': admission, 'prior_candidate': challenge, 'input_hashes': before,
              'prepared_tree': tree_hash(destination), 'source_unchanged': tree_hash(destination / 'source') == task['source_sha256']})
    finally:
        post = {'inputs_unchanged': before == inputs(),
                'remaining_owned_containers': runner.control(['ps', '-aq', '--filter',
                    'label=corecoder.sandbox.owner=' + runner.owner(root)]).decode().split()}
        write(root / 'preparation-postflight.json', post)
        if not post['inputs_unchanged'] or post['remaining_owned_containers']:
            raise ValueError('Preparation integrity or cleanup failed')
    print('Offline admission complete: base target 0/1, preserve 9/9; prior candidate preserve 5/9.', flush=True)


def live(root):
    frozen()
    preparation = read(root / 'preparation.json')
    post = read(root / 'preparation-postflight.json')
    prepared, output = root / 'prepared', root / 'live'
    if (preparation['status'] != 'ready_for_repair' or not post['inputs_unchanged']
            or post['remaining_owned_containers'] or output.exists() or (root / 'run-plan.json').exists()
            or tree_hash(prepared) != preparation['prepared_tree'] or inputs() != preparation['input_hashes']):
        raise ValueError('Admission, input integrity, or single-invocation guard failed')
    task, settings = trusted_task(prepared, CONFIG)
    policy = runner.preflight(settings['image'])
    if policy['image_id'] != task['sandbox']['image_id']:
        raise ValueError('Pinned image changed')
    model = next(row for row in local_get('tags')['models'] if row['name'] == MODEL)
    if model['digest'] != DIGEST:
        raise ValueError('Installed model differs from the fixed model')
    before = inputs()
    write(root / 'run-plan.json', {'method_round': 2, 'new_task_runs_before': 1, 'planned_new_task_runs': 1,
          'model': model, 'thinking': False, 'cloud_calls': 0, 'sandbox': policy, 'input_hashes': before,
          'prepared_tree': tree_hash(prepared), 'source_sha256': task['source_sha256'],
          'harness_sha256': task['harness_sha256'], 'observation_policy': 'compact-v1',
          'context_policy': 'baseline', 'workflow': 'symbol-recovery-v1',
          'token_budget': 60000, 'max_steps': 20, 'max_edit_attempts': 6, 'max_output_tokens': 4096,
          'max_consecutive_errors': 3, 'max_repeated_actions': 3, 'context_tokens': 65536, 'wall_timeout': 1200,
          'scope': 'Development-check expansion, original source restart; not a held-out or same-test comparison.',
          'resident_before': local_get('ps')})
    started = time.monotonic()
    try:
        execute(prepared, CONFIG, output, mode='ollama', model=MODEL, workflow='symbol-recovery-v1',
                context_policy='baseline', observation_policy='compact-v1')
    finally:
        report = read(output / 'report.json') if (output / 'report.json').is_file() else None
        after_model = next(row for row in local_get('tags')['models'] if row['name'] == MODEL)
        post = {'elapsed_seconds': time.monotonic() - started, 'inputs_unchanged': before == inputs(),
                'prepared_unchanged': tree_hash(prepared) == preparation['prepared_tree'],
                'model_digest_unchanged': after_model['digest'] == DIGEST,
                'remaining_owned_containers': runner.control(['ps', '-aq', '--filter',
                    'label=corecoder.sandbox.owner=' + runner.owner(output)]).decode().split(),
                'fresh_model_calls': report['fresh_model_calls'] if report else None,
                'report_sha256': sha(output / 'report.json') if report else None}
        write(root / 'postflight.json', post)
        print(json.dumps({'postflight': post, 'result': {key: report.get(key) for key in (
            'status', 'public_checks_passed', 'accepted', 'delivery_status', 'fresh_model_calls',
            'edit_attempts_used', 'metrics')} if report else None}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prepare', 'live'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Output must be a project .tmp directory on D:')
    (prepare if args.phase == 'prepare' else live)(output)


if __name__ == '__main__':
    main()
