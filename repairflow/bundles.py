"""Export frozen tasks without reference fixes; load only local trusted bundles."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from evals.runner import digest, snapshot
from evals.schema import relative_path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / '.tmp/real-defects/system-comparison-v1-rerun/manifest.json'
HISTORY = ROOT / '.tmp/real-defects/coverage-full-repair-v1-20261010'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def tree_hash(path):
    path = Path(path)
    if not path.is_dir() or path.is_symlink() or any(p.is_symlink() for p in path.rglob('*')):
        raise ValueError('Bundle directories must exist and contain no links')
    return digest(snapshot(path))


def export(task_id, output, include_replay=False):
    """One-time migration from frozen experimental assets to a self-contained bundle."""
    manifest = read(MANIFEST)
    cases = [c for c in manifest['cases'] if c['task_id'] == task_id]
    if not manifest['complete'] or len(cases) != 1:
        raise ValueError('Unknown frozen task')
    case = cases[0]
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Bundle output must be new')
    for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
        source = Path(case[key]).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('Bundle overlaps frozen inputs')
        if tree_hash(source) != case[key + '_hash']:
            raise ValueError('Frozen task changed: ' + key)
    output.mkdir(parents=True)
    data = {k: case[k] for k in ('task_id', 'repo', 'package', 'source_root', 'description',
                                 'description_hash', 'allowed_files')}
    data.update(schema_version=1, strategy='coverage-v2-constrained-v1', hashes={})
    for name, key in (('source', 'before'), ('public', 'harness'), ('frozen', 'frozen_harness'), ('grader', 'checks')):
        shutil.copytree(case[key], output / name)
        data['hashes'][name] = tree_hash(output / name)
    if task_id == 'click-flag-envvar':
        from docs.experiments.flag_contract_v1 import write_harness

        write_harness(output / 'contract')
        data['hashes']['contract'] = tree_hash(output / 'contract')
    if include_replay:
        history = read(HISTORY / 'experiment.json')
        rows = [r for r in history['runs'] if r['task_id'] == task_id and r['policy'] == 'deepseek-high']
        if not history['complete'] or len(rows) != 1:
            raise ValueError('Require a completed historical task')
        record = rows[0]
        # Multi-round feedback contains timing observations: do not pretend it is exact replay.
        if record['worker']['metrics']['llm_calls'] != 1 or not record['accepted']:
            raise ValueError('Replay export requires a successful single-call task')
        folder = HISTORY / task_id / 'deepseek-high'
        messages = read(folder / 'initial-messages.json')
        content = (folder / 'initial-response.txt').read_text(encoding='utf-8')
        call = record['worker']['provider_calls'][0]
        replay = {'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
                  'content': content, 'call': call, 'source': 'historical response; no fresh inference'}
        write(output / 'replay.json', replay)
        data['replay_sha256'] = hashlib.sha256((output / 'replay.json').read_bytes()).hexdigest()
    write(output / 'bundle.json', data)
    load(output)
    return output


def load(root):
    root = Path(root).resolve()
    if (root / 'bundle.json').is_symlink():
        raise ValueError('Linked metadata is unsupported')
    data = read(root / 'bundle.json')
    if (data.get('schema_version') != 1 or data.get('strategy') != 'coverage-v2-constrained-v1'
            or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}', data['task_id'])):
        raise ValueError('Unsupported bundle')
    expected = {'source', 'public', 'frozen', 'grader'}
    if data['task_id'] == 'click-flag-envvar':
        expected.add('contract')
    if set(data['hashes']) != expected:
        raise ValueError('Incomplete bundle hashes')
    for name, sha in data['hashes'].items():
        if tree_hash(root / name) != sha:
            raise ValueError('Bundle input changed: ' + name)
    if hashlib.sha256(data['description'].encode()).hexdigest() != data['description_hash']:
        raise ValueError('Bundle description changed')
    allowed = data['allowed_files']
    if not allowed or len(set(allowed)) != len(allowed):
        raise ValueError('Invalid allowed files')
    for name in allowed:
        relative_path(name)
        if not name.endswith('.py') or not (root / 'source' / name).is_file():
            raise ValueError('Invalid allowed source')
    relative_path(data['source_root'])
    if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', data['package']):
        raise ValueError('Invalid package')
    if 'replay_sha256' in data:
        p = root / 'replay.json'
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != data['replay_sha256']:
            raise ValueError('Replay record changed')
    data['bundle_hash'] = hashlib.sha256((root / 'bundle.json').read_bytes()).hexdigest()
    return data
