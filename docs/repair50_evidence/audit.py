"""Offline, stdlib-only verification of the bundled 43/50 -> 47/50 evidence."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path, PureWindowsPath

FILES = ('baseline.json', 'candidate.json', 'manifest.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_excerpts(folder):
    index = read(folder / 'cases' / 'index.json')
    names = set()
    for item in index['files']:
        relative = Path(item['file'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'Invalid excerpt path')
        require(item['file'] not in names, 'Duplicate excerpt')
        require(sha(folder / relative) == item['sha256'], 'Excerpt changed: ' + item['file'])
        names.add(item['file'])
    return len(names)


def group_ok(group):
    return (group.get('returncode') == 0 and group.get('timed_out') is False
            and group.get('tests_run', 0) > 0 and group.get('successful') is True
            and all(group.get(k) == 0 for k in ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes')))


def groups_ok(groups, names):
    require(set(groups) == set(names), 'Unexpected test groups')
    for group in groups.values():
        require(group.get('passed') is group_ok(group), 'Test flag disagrees with raw result')
    return all(group_ok(g) for g in groups.values())


def verify_run(report, cases):
    require(report['complete'] is True and len(report['runs']) == len(cases), 'Incomplete run')
    rows = {r['task_id']: r for r in report['runs']}
    require(len(rows) == len(cases) and set(rows) == set(cases), 'Missing, duplicate or unexpected tasks')
    require(report['protocol']['tasks'] == list(cases), 'Task order changed')
    counts = Counter()
    for task, row in rows.items():
        require(row['policy'] == 'deepseek-high', 'Unexpected model policy')
        worker, grading = row['worker'], row['verification']
        metrics, calls = worker['metrics'], worker['provider_calls']
        require(row['process']['returncode'] == 0 and not row['process']['timed_out'], 'Worker failure: ' + task)
        require(1 <= len(calls) <= 2 and metrics['llm_calls'] == len(calls), 'Invalid call count: ' + task)
        require(metrics['missing_usage_calls'] == 0, 'Missing measured usage: ' + task)
        for call in calls:
            require(call['response_received'] and call['model_returned'] == 'deepseek-flash', 'Invalid provider response')
            require(call['total_tokens'] == call['prompt_tokens'] + call['completion_tokens'], 'Invalid provider usage')
        prompt = sum(c['prompt_tokens'] for c in calls)
        completion = sum(c['completion_tokens'] for c in calls)
        require(metrics['prompt_tokens'] == prompt and metrics['completion_tokens'] == completion, 'Usage disagrees: ' + task)
        require(metrics['budget_accounted_tokens'] == prompt + completion <= 60000, 'Budget accounting disagrees: ' + task)
        public = groups_ok(row['public'], ('Reproduce', 'Preserve'))
        frozen = groups_ok(row['frozen'], ('Reproduce', 'Preserve'))
        independent = groups_ok(grading['groups'], ('Target', 'Controls')) and not grading['scope_violations']
        require(grading['passed'] is independent, 'Independent grading flag disagrees: ' + task)
        require(set(grading['changed_files']) <= set(cases[task]['allowed_files']), 'Edit outside allowed source')
        final = worker.get('final_checks', {})
        expected = {'public', 'frozen', 'contract'} if task == 'click-flag-envvar' else {'public', 'frozen'}
        final_ok = set(final) == expected and all(groups_ok(v, ('Reproduce', 'Preserve')) for v in final.values())
        accepted = worker['status'] == 'completed' and independent and public and frozen and final_ok
        require(row['accepted'] is accepted, 'Acceptance predicate disagrees: ' + task)
        counts.update(passed=int(accepted), calls=len(calls), prompt_tokens=prompt, completion_tokens=completion,
                      tokens=prompt + completion, controls=int(grading['groups']['Controls']['passed']))
    stored = report['summary']['deepseek-high']
    for key in ('passed', 'calls', 'tokens'):
        require(stored[key] == counts[key], 'Stored summary disagrees: ' + key)
    require(stored['tasks'] == len(cases), 'Stored task count disagrees')
    return rows, dict(counts)


def compare(manifest, baseline, candidate, expected_tasks=50):
    require(manifest['complete'] is True, 'Incomplete task manifest')
    cases = {c['task_id']: c for c in manifest['cases']}
    require(len(cases) == len(manifest['cases']) == expected_tasks, 'Unexpected task pool size')
    require(baseline['protocol']['config'] == candidate['protocol']['config'], 'Model or budget configuration changed')
    config = candidate['protocol']['config']
    require(config['model'] == 'deepseek-flash' and config['reasoning_effort'] == 'high', 'Unexpected model config')
    require(baseline['protocol']['request_settings'] == candidate['protocol']['request_settings'], 'Request settings changed')
    for case in cases.values():
        require(case['admitted'] is True, 'Task did not pass admission')
        before, after = case['admission']['before'], case['admission']['after']
        require(not group_ok(before['Target']) and before['Target']['returncode'] == 1
                and before['Target']['failures'] + before['Target']['errors'] > 0
                and not before['Target']['timed_out']
                and before['Target']['tests_run'] > 0 and group_ok(before['Controls'])
                and group_ok(after['Target']) and group_ok(after['Controls']), 'Admission evidence invalid')
    old, old_cost = verify_run(baseline, cases)
    new, new_cost = verify_run(candidate, cases)
    gained, lost, rows = [], [], []
    for task, case in cases.items():
        a, b = old[task], new[task]
        if not a['accepted'] and b['accepted']:
            gained.append(task)
        if a['accepted'] and not b['accepted']:
            lost.append(task)
        rows.append({'task_id': task, 'repo': case['repo'], 'historical_split': case['split'],
                     'before_passed': a['accepted'], 'after_passed': b['accepted'],
                     'before_tokens': a['worker']['metrics']['budget_accounted_tokens'],
                     'after_tokens': b['worker']['metrics']['budget_accounted_tokens'],
                     'after_status': b['worker']['status'], 'after_calls': b['worker']['metrics']['llm_calls'],
                     'after_target_passed': b['verification']['groups']['Target']['passed'],
                     'after_controls_passed': b['verification']['groups']['Controls']['passed']})
    return {'tasks': len(cases), 'before': old_cost, 'after': new_cost, 'gained': gained, 'lost': lost,
            'net_gain': len(gained) - len(lost), 'percentage_point_gain': (new_cost['passed'] - old_cost['passed']) * 100 / len(cases),
            'token_change_percent': round(100 * (new_cost['tokens'] / old_cost['tokens'] - 1), 2),
            'by_repo': {repo: {'tasks': len(rr := [r for r in rows if r['repo'] == repo]),
                              'before_passed': sum(r['before_passed'] for r in rr),
                              'after_passed': sum(r['after_passed'] for r in rr)} for repo in sorted({r['repo'] for r in rows})},
            'historical_splits': dict(Counter(c['split'] for c in cases.values())),
            'admission_target_outcomes': {
                'with_assertion_failures': sum(c['admission']['before']['Target']['failures'] > 0 for c in cases.values()),
                'with_errors': sum(c['admission']['before']['Target']['errors'] > 0 for c in cases.values())},
            'call_distribution': {'before': dict(Counter(len(r['worker']['provider_calls']) for r in old.values())),
                                  'after': dict(Counter(len(r['worker']['provider_calls']) for r in new.values()))},
            'provider_fingerprints': {'before': dict(Counter(c.get('system_fingerprint') for r in old.values() for c in r['worker']['provider_calls'])),
                                      'after': dict(Counter(c.get('system_fingerprint') for r in new.values() for c in r['worker']['provider_calls']))},
            'rows': rows, 'cost_usd': None,
            'scope': 'Known-pool historical comparison; no causal, unseen-Issue, Docker-era or production-accuracy claim.'}


def tree_hash(root):
    require(root.is_dir() and not root.is_symlink(), 'Missing or linked asset: ' + str(root))
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*'), key=lambda p: p.relative_to(root).as_posix()):
        name = path.relative_to(root)
        if any(p in {'__pycache__', '.eval-logs'} for p in name.parts):
            continue
        require(not path.is_symlink(), 'Linked asset')
        if path.is_file():
            digest.update(name.as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def verify_local(manifest, reports, metadata, root):
    def path(recorded):
        relative = PureWindowsPath(recorded).relative_to(PureWindowsPath(metadata['original_workspace']))
        require('..' not in relative.parts, 'Asset escapes workspace')
        return root.joinpath(*relative.parts)

    checked = set()
    for report in reports:
        for recorded, expected in report['protocol']['input_hashes'].items():
            key = (recorded, expected)
            if key not in checked:
                require(sha(path(recorded)) == expected, 'Frozen input changed: ' + recorded)
                checked.add(key)
    trees = set()
    for case in manifest['cases']:
        for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
            item = (case[key], case[key + '_hash'])
            if item not in trees:
                require(tree_hash(path(item[0])) == item[1], 'Frozen tree changed: ' + item[0])
                trees.add(item)
    return {'frozen_files_verified': len(checked), 'frozen_trees_verified': len(trees), 'inference_or_tests_executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh output directory')
    parser.add_argument('--verify-local-assets', action='store_true')
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    metadata = read(folder / 'inputs.json')
    for name in FILES:
        require(sha(folder / 'inputs' / name) == metadata['sha256'][name], 'Bundled input changed: ' + name)
    baseline, candidate, manifest = (read(folder / 'inputs' / name) for name in FILES)
    result = compare(manifest, baseline, candidate)
    result['input_sha256'] = metadata['sha256']
    result['excerpts_verified'] = verify_excerpts(folder)
    if args.verify_local_assets:
        result['local_assets'] = verify_local(manifest, (baseline, candidate), metadata, args.source_root.resolve())
    require(not args.output.exists(), 'Use a fresh output directory')
    args.output.mkdir(parents=True)
    (args.output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (args.output / 'tasks.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result['rows'][0]))
        writer.writeheader()
        writer.writerows(result['rows'])
    print(json.dumps({k: result[k] for k in ('tasks', 'before', 'after', 'gained', 'lost', 'token_change_percent')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
