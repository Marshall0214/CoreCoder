"""Frozen development suite over admitted real tasks; no hidden feedback to workers."""

import argparse
import hashlib
import json
import re
from dataclasses import fields
from pathlib import Path

from .real_admission import DATA, load_cases
from .real_tasks import admitted_case, run_real
from .runner import implementation_metadata, write_summary
from .schema import RunConfig, relative_path


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('schema_version') != 1 or data.get('split') != 'development'
            or not re.fullmatch(r'[a-z0-9-]+', data.get('suite_id', ''))):
        raise ValueError('Expected a versioned development suite')
    if data.get('workflow', 'agent-loop') not in {'agent-loop', 'staged'}:
        raise ValueError('Unsupported suite workflow')
    repeat = data.get('repeat')
    if type(repeat) is not int or not 1 <= repeat <= 10:
        raise ValueError('Repeat must be between 1 and 10')
    expected = {field.name for field in fields(RunConfig)}
    # Preserve the historical v1 manifest: these newly introduced policies were fixed/full there.
    legacy = expected - {'output_policy', 'read_policy'}
    if set(data['config']) != expected and not (
            data['suite_id'] == 'click-development-v1' and set(data['config']) == legacy):
        raise ValueError('Suite must explicitly freeze every RunConfig field')
    config = RunConfig(**data['config'])
    if data.get('workflow') == 'staged' and config.context_policy != 'none':
        raise ValueError('Staged workflow organizes its own context')
    if (config.mode != 'live' or config.search_backend != 'off' or config.context_policy not in {'none', 'read-dedup', 'read-window'}
            or config.prompt_policy != 'baseline' or config.search_history != 'full'):
        raise ValueError('This suite supports the default or budget-aware agent-loop protocol only')
    entries, groups, ids = [], set(), set()
    for source in data['sources']:
        name = source['name']
        if not re.fullmatch(r'[a-z0-9-]+', name) or name in groups:
            raise ValueError('Source names must be unique portable identifiers')
        groups.add(name)
        catalog = path.parent / relative_path(source['catalog'])
        if file_hash(catalog) != source['catalog_sha256']:
            raise ValueError('Catalog changed; version the suite explicitly')
        cases = load_cases(catalog)
        if source['tasks'] != [case['case_id'] for case in cases]:
            raise ValueError('Frozen task order must match the complete source catalog')
        for case in cases:
            if case['case_id'] in ids:
                raise ValueError('Duplicate task across source catalogs')
            ids.add(case['case_id'])
            entries.append((name, catalog, case['case_id']))
    if not entries:
        raise ValueError('Suite must contain admitted tasks')
    return data, entries


def prepare(entries, admissions):
    if set(admissions) != {entry[0] for entry in entries}:
        raise ValueError('Supply exactly one admission per suite source')
    prepared = [admitted_case(admissions[name], catalog, task) for name, catalog, task in entries]
    environment = prepared[0][-1]
    if any(case[-1] != environment for case in prepared):
        raise ValueError('All admissions must use the same recorded test environment')
    return prepared


def run_suite(manifest, admissions, output, mode, repeat=None, diagnostic_overrides=None):
    data, entries = load_manifest(manifest)
    if mode not in {'unchanged', 'reference', 'scripted', 'live'}:
        raise ValueError('Unsupported suite mode')
    repeat = data['repeat'] if repeat is None else repeat
    if type(repeat) is not int or not 1 <= repeat <= 10:
        raise ValueError('Repeat must be between 1 and 10')
    workflow = data.get('workflow', 'agent-loop')
    if workflow == 'staged' and mode != 'live':
        raise ValueError('Staged suite requires live mode')
    prepared = prepare(entries, admissions)  # Validate every snapshot before starting any run.
    overrides = diagnostic_overrides or {}
    if set(overrides) - {'token_budget', 'max_rounds', 'wall_timeout'}:
        raise ValueError('Only budget, rounds and timeout may vary in diagnostic runs')
    config = RunConfig(**dict(data['config'], mode=mode, **overrides))
    output = output.resolve()
    for case in prepared:
        for protected in (case[2], case[3]):
            if output.is_relative_to(protected.resolve()):
                raise ValueError('Suite output must stay outside source and checks')
    output.mkdir(parents=True, exist_ok=False)
    report = {'suite_id': data['suite_id'], 'split': 'development', 'benchmark_eligible': False,
              'manifest_sha256': file_hash(manifest), 'manifest': data,
              'admissions': {name: {'path': str(path.resolve()), 'sha256': file_hash(path)}
                             for name, path in admissions.items()},
              'config': config.to_dict(), 'workflow': workflow, 'repeat': repeat,
              'diagnostic_overrides': overrides,
              'expected_runs': len(entries) * repeat, 'complete': False, 'runs': [],
              'implementation': implementation_metadata()}

    def save():
        report['completed_runs'] = len(report['runs'])
        report['complete'] = (len(report['runs']) == report['expected_runs']
                              and not any(row['status'] == 'cancelled' for row in report['runs']))
        (output / 'suite-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for repetition in range(1, repeat + 1):
        for case in prepared:
            options = {'workflow': workflow} if workflow != 'agent-loop' else {}
            row = run_real(*case, config, output / 'runs', **options)
            row['repetition'] = repetition
            report['runs'].append(row)
            save()  # Failed runs remain in the denominator; preserve progress on interruption.
            print(f"{repetition}/{repeat} {row['task_id']}: {row['status']}", flush=True)
            if row['status'] == 'cancelled':
                write_summary(report['runs'], output)
                return report
    write_summary(report['runs'], output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=DATA / 'development-suite-v1.json')
    parser.add_argument('--admission', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('unchanged', 'reference', 'scripted', 'live'), required=True)
    parser.add_argument('--repeat', type=int, help='Recorded override; default is the frozen suite repeat')
    args = parser.parse_args()
    admissions = {}
    for value in args.admission:
        name, separator, path = value.partition('=')
        if not separator or not path or name in admissions:
            parser.error('Admissions must be unique SOURCE=PATH entries')
        admissions[name] = Path(path).resolve()
    if args.mode == 'live':
        from corecoder.config import _load_dotenv

        _load_dotenv()
    report = run_suite(args.suite.resolve(), admissions, args.output, args.mode, args.repeat)
    print(args.output.resolve() / 'suite-report.json')
    expected = 'failed_verification' if args.mode == 'unchanged' else 'passed'
    return 0 if report['complete'] and all(row['status'] == expected for row in report['runs']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
