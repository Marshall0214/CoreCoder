"""Freeze this fresh PPC run without changing its original artifacts."""
import hashlib
import json
import shutil
from pathlib import Path

from integrations import harness2 as bridge
from integrations.harness2_runtime import ROOT, UPSTREAM

SOURCE = ROOT / '.tmp/harness2-indexed-ppc-20261106'
PACKET = ROOT / 'docs/harness2_ppc_20261106'


def freeze():
    result = bridge.read(SOURCE / 'report.json')
    assert result['status'] in ('completed', 'completed_with_ppc_error', 'failed')
    assert bridge.read(SOURCE / 'audit.json')['checks_passed']
    PACKET.mkdir(parents=True, exist_ok=False)
    sources = [(path, Path('run') / path.relative_to(SOURCE)) for path in sorted(SOURCE.rglob('*'))
               if path.is_file() and not any(part in {'state', '__pycache__', '.pytest_cache'}
                                            for part in path.relative_to(SOURCE).parts)]
    for name in ('validate_harness2_ppc_20261106.py', 'check_harness2_ppc_20261106.py',
                 'publish_harness2_ppc_20261106.py', 'recover_harness2_ppc_20261106.py',
                 'freeze_harness2_ppc_20261106.py'):
        sources.append((ROOT / '.tmp' / name, Path('helpers') / name))
    sources.append((ROOT / 'integrations/harness2-source.json', Path('upstream/source-manifest.json')))
    origin = bridge.read(ROOT / 'integrations/harness2-source.json')
    for name in origin['files']:
        sources.append((UPSTREAM / name, Path('upstream/source') / name))
    rows = []
    for source, relative in sources:
        assert not source.is_symlink()
        target = PACKET / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert bridge.sha(source) == bridge.sha(target)
        rows.append({'path': relative.as_posix(), 'bytes': target.stat().st_size, 'sha256': bridge.sha(target)})
    manifest = {'schema': 'fresh-indexed-ppc-evidence-v1', 'experiment': SOURCE.name,
                'file_count': len(rows), 'bytes': sum(row['bytes'] for row in rows),
                'includes_failed_attempts': True, 'excludes': ['state caches', '__pycache__', '.pytest_cache'],
                'files': rows}
    bridge.write(PACKET / 'manifest.json', manifest)
    for row in rows:
        path = PACKET / row['path']
        assert path.stat().st_size == row['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
    print(json.dumps({key: manifest[key] for key in ('file_count', 'bytes')}))


if __name__ == '__main__':
    freeze()
