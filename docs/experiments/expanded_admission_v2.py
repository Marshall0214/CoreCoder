"""Re-admit the frozen 30 cases plus 20 pinned upstream defects before inference."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from docs.experiments import expanded_admission_v1 as previous
from evals.real_admission import extract_archive
from evals.runner import digest, snapshot

ROOT = previous.ROOT
DATA = Path(__file__).with_name('expanded_suite_v2')
groups = previous.groups
PYTHON = previous.PYTHON
history = previous.history


def download(case, output):
    directory = output / case['task_id']
    directory.mkdir()
    metadata_path = ROOT / '.tmp/expanded-research-v1' / (case['after_commit'] + '.json')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    if metadata['sha'] != case['after_commit'] or metadata['parents'][0]['sha'] != case['before_commit']:
        raise ValueError('Fix/parent mismatch')
    shutil.copyfile(metadata_path, directory / 'commit-metadata.json')
    for label in ('before', 'after'):
        cached = ROOT / '.tmp/expanded-research-v1/archives' / (case[label + '_commit'] + '.zip')
        if not cached.exists():
            pending = cached.with_suffix('.pending.zip')
            subprocess.run(['curl.exe', '--retry', '3', '--fail', '--location', '--silent', '--show-error',
                            '--max-time', '45', '--output', str(pending),
                            f"https://codeload.github.com/{case['repo']}/zip/{case[label + '_commit']}"],
                           check=True, capture_output=True, timeout=190)
            pending.replace(cached)
        archive = cached.read_bytes()
        if len(archive) > 32000000:
            raise ValueError('Source archive too large')
        extract_archive(archive, directory / label)
    before = directory / 'before'
    if not list(before.glob('*LICENSE*')) and not list(before.glob('*COPYING*')):
        raise ValueError('Missing preserved upstream license')
    allowed = sorted(p.relative_to(before).as_posix() for p in (before / case['package']).rglob('*.py')
                     if 'tests' not in p.relative_to(before).parts)
    return dict(case, before=str(before.resolve()), after=str((directory / 'after').resolve()),
                checks=str((DATA / 'checks' / case['task_id']).resolve()),
                allowed_files=allowed, previously_inspected=False)


def run(base, output):
    data = json.loads(base.read_text(encoding='utf-8'))
    if not data['complete'] or len(data['cases']) != 30:
        raise ValueError('Require the certified 30-task admission')
    if output.exists():
        raise ValueError('Fresh output required')
    catalog = json.loads((DATA / 'new-candidates.json').read_text(encoding='utf-8'))
    if len(catalog['cases']) != 20:
        raise ValueError('Require 20 new candidates')
    identifiers = [c['task_id'] for c in data['cases'] + catalog['cases']]
    if len(set(identifiers)) != 50:
        raise ValueError('Duplicate tasks')
    output.mkdir(parents=True)
    cases = data['cases'].copy()
    for item in catalog['cases']:
        row = download(item, output)
        row['checks'] = str((DATA / 'checks' / item['task_id']).resolve())
        cases.append(row)
    report = {'protocol': 'expanded-admission-v2', 'complete': False, 'model_calls': 0,
              'base_sha256': history.sha(base), 'catalog_sha256': history.sha(DATA / 'new-candidates.json'),
              'adapter_sha256': history.sha(Path(__file__)), 'cases': []}
    for case in cases:
        if case.get('before_hash'):
            for source, key in [('before', 'before_hash'), ('after', 'after_hash'), ('checks', 'checks_hash')]:
                if digest(snapshot(Path(case[source]))) != case[key]:
                    raise ValueError('Frozen historical input changed')
        outcomes = {label: groups(Path(case[label]), Path(case['checks']), case['package'],
                                 case['source_root'], output / 'admission-logs' / case['task_id'] / label)
                    for label in ('before', 'after')}
        target = outcomes['before']['Target']
        admitted = (target.get('tests_run', 0) > 0 and not target['timed_out'] and not target['passed']
                    and target.get('failures', 0) + target.get('errors', 0) > 0
                    and outcomes['before']['Controls']['passed']
                    and all(g['passed'] for g in outcomes['after'].values()))
        report['cases'].append(dict(case, admitted=admitted, admission=outcomes,
                                   before_hash=digest(snapshot(Path(case['before']))),
                                   after_hash=digest(snapshot(Path(case['after']))),
                                   checks_hash=digest(snapshot(Path(case['checks'])))))
        (output / 'admission.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(case['task_id'], 'admitted' if admitted else 'REJECTED', flush=True)
    report['complete'] = len(report['cases']) == 50 and all(c['admitted'] for c in report['cases'])
    (output / 'admission.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.base.resolve(), args.output.resolve())
