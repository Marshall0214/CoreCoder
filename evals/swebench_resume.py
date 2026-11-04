"""Audited transport-only recovery of a frozen Mini batch; never retry completed inference."""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

from evals import swebench_batch as batch
from evals.swebench_images import ImageTransfer
from evals.swebench_mini import ROOT, sha, write


def cache_link(source, target):
    try:
        os.link(source, target)
    except OSError:
        # Windows sandbox policies or filesystems can prohibit hardlinks.
        shutil.copyfile(source, target)


class ResumableTransfer(ImageTransfer):
    """Retain verified shared layers and tolerate slow transfers while bytes advance."""
    def __init__(self, folder, proxy='http://127.0.0.1:7890'):
        super().__init__(folder, proxy)
        self.cache = folder.parents[2] / 'verified-layer-cache'
        self.cache.mkdir(exist_ok=True)
        self.deadlines = {}

    def note(self, **values):
        with (self.folder / 'transfer.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time': time.time(), **values}) + '\n')

    def descriptors(self):
        path = self.folder / 'manifest.json'
        if not path.exists():
            return []
        manifest = json.loads(path.read_bytes())
        return [manifest['config'], *manifest['layers']] if 'layers' in manifest else []

    def remember(self, path, descriptor):
        digest = descriptor['digest'].removeprefix('sha256:')
        if path.stat().st_size != descriptor['size'] or sha(path) != digest:
            return False
        target = self.cache / digest
        if target.exists() and (target.stat().st_size != descriptor['size'] or sha(target) != digest):
            target.unlink()
        if not target.exists():
            # Same D: filesystem; task cleanup drops its link while cache keeps the data.
            cache_link(path, target)
        os.utime(target, None)
        return True

    def restore(self):
        for row in self.descriptors():
            digest = row['digest'].removeprefix('sha256:')
            target, cached = self.folder / digest, self.cache / digest
            if target.exists():
                self.remember(target, row)
            elif cached.exists() and cached.stat().st_size == row['size'] and sha(cached) == digest:
                cache_link(cached, target)
                os.utime(cached, None)
                self.note(event='verified_cache_hit', digest=digest, size=row['size'])

    def metadata(self, url, destination, header=None):
        raw = super().metadata(url, destination, header)
        if destination.name == 'manifest.json':
            self.restore()
        return raw

    def fetch(self, url, destination, header=None, resume=False, seconds=60):
        if not resume:
            return super().fetch(url, destination, header, resume, seconds)
        digest = destination.name.removesuffix('.part')
        descriptor = next((row for row in self.descriptors() if row['digest'] == 'sha256:' + digest), None)
        if descriptor is None:
            raise ValueError('Resume requires a pinned manifest descriptor')
        deadline = self.deadlines.setdefault(digest, time.monotonic() + 3600)
        stalled, code = 0, 1
        while time.monotonic() < deadline:
            before = destination.stat().st_size if destination.exists() else 0
            code = super().fetch(url, destination, header, True, seconds=120)
            actual = destination.stat().st_size if destination.exists() else 0
            self.note(event='blob_progress', digest=digest, before=before, actual=actual,
                      expected=descriptor['size'], curl_exit=code)
            if actual == descriptor['size']:
                if self.remember(destination, descriptor):
                    return 0
                self.note(event='checksum_mismatch', digest=digest)
                return 1
            if code == 22 or actual > descriptor['size']:
                return code or 1  # Original loader refreshes auth and rejects oversized data.
            stalled = stalled + 1 if actual <= before else 0
            if stalled >= 4 or code not in {0, 18, 28, 35, 56, 92}:
                return code or 1
        self.note(event='blob_deadline', digest=digest)
        return code or 28

    def load(self, tag):
        self.restore()
        result = super().load(tag)
        # Bound only the newly created shared cache; never touch other image stores.
        files = sorted(self.cache.iterdir(), key=lambda path: path.stat().st_mtime)
        size = sum(path.stat().st_size for path in files)
        for path in files:
            if size <= 12_000_000_000:
                break
            size -= path.stat().st_size
            path.unlink()
        return result


def requeue(output, recovery):
    """Called under the original batch lock, before any resumed image/model operation."""
    path = output / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    before = path.read_bytes()
    keys = []
    for key, state in report['tasks'].items():
        if state.get('status') != 'infra_error' or state.get('phase') != 'image':
            continue
        if (output / 'tasks' / key / 'agent').exists() or state.get('fresh_model_calls', 0):
            raise ValueError('Refuse image retry after any inference')
        keys.append(key)
    recovery.mkdir(parents=True, exist_ok=False)
    (recovery / 'report-before.json').write_bytes(before)
    (recovery / 'transport-source.py').write_bytes(Path(__file__).read_bytes())
    protected = {}
    for key, state in report['tasks'].items():
        if state.get('status') == 'graded':
            protected[key] = {str(path.relative_to(output)): sha(path)
                              for path in (output / 'tasks' / key).rglob('*')
                              if path.is_file() and 'image-cache' not in path.parts}
    write(recovery / 'admission.json', {
        'phase': 'transport_only', 'source_sha256': sha(Path(__file__)),
        'frozen_protocol_sha256': sha(output / 'protocol.json'), 'requeued_image_tasks': keys,
        'agent_and_grader_code_unchanged': True, 'protected_completed_tasks': protected,
        'automatic_model_retry': False})
    for key in keys:
        state = report['tasks'][key]
        state.setdefault('infrastructure_history', []).append({name: state[name] for name in
                                                             ('status', 'phase', 'error_type') if name in state})
        state.update(status='preparing', phase='image')
        state.pop('error_type', None)
    report.update(status='resuming_infrastructure', recovery=str(recovery.relative_to(output)))
    report['summary'] = batch.aggregate(json.loads((output / 'protocol.json').read_text(encoding='utf-8'))['instance_ids'],
                                        report['tasks'])
    batch.save(path, report)


def run(output):
    original = batch.execute
    recovery = output / 'recovery' / time.strftime('%Y%m%d-%H%M%S')

    def execute(folder, protocol, resume):
        requeue(folder, recovery)
        # Seed verified bytes already downloaded for any previously failed task.
        for cache in sorted((folder / 'tasks').glob('*/image-cache')):
            ResumableTransfer(cache).restore()
        return original(folder, protocol, resume)

    try:
        batch.ImageTransfer, batch.execute = ResumableTransfer, execute
        return batch.run(output, resume=True)  # Retain frozen code/model validation and the original OS lock.
    finally:
        batch.ImageTransfer, batch.execute = ImageTransfer, original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    args = parser.parse_args()
    output = args.batch.resolve()
    if not output.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and output.drive.lower() != 'd:'):
        parser.error('Use the existing frozen D: project batch')
    print(json.dumps(run(output)['summary']))


if __name__ == '__main__':
    main()
