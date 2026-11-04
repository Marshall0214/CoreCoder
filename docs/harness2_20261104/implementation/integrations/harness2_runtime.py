"""Pinned upstream loader and Windows file-lock adapter for the stdlib-only core."""
import os
import sys
import time
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '6868817518876de8fd170c6a8354daca273b6191'
UPSTREAM = ROOT / '.tmp/harness2-source-20261104'


def windows_locks():
    if os.name != 'nt':
        return
    import msvcrt

    module = ModuleType('fcntl')
    module.LOCK_EX, module.LOCK_SH, module.LOCK_UN, module.LOCK_NB = 2, 1, 8, 4

    def flock(file, operation):
        descriptor = file if isinstance(file, int) else file.fileno()
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if operation & module.LOCK_UN:
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                return
            # Shared locks are conservatively exclusive. Only the upstream summary writer uses this.
            deadline = time.monotonic() + 60
            while True:
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    if operation & module.LOCK_NB or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
        finally:
            os.lseek(descriptor, position, os.SEEK_SET)

    module.flock = flock
    sys.modules.setdefault('fcntl', module)


def load():
    import hashlib
    import json

    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError('Run the Harness2 controller with Python 3.12 or 3.13')
    if json.loads((UPSTREAM / 'source-origin.json').read_text(encoding='utf-8'))['commit'] != COMMIT:
        raise ValueError('Pinned upstream source mismatch')
    expected = json.loads((ROOT / 'integrations/harness2-source.json').read_text(encoding='utf-8'))
    for name, digest in expected['files'].items():
        path = UPSTREAM / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Upstream source changed: ' + name)
    if (UPSTREAM / '.env').exists():
        raise ValueError('Do not place model credentials in the isolated upstream tree')
    sys.path.insert(0, str(UPSTREAM))
    windows_locks()
    if os.name == 'nt':
        from harness2.core import tree

        if not getattr(tree, '_corecoder_posix_keys', False):
            original = tree.read_tree

            def read_tree(*args, **kwargs):
                result = original(*args, **kwargs)
                if kwargs.get('rejected') is not None:
                    stubs = {name for name, _ in args[0].stubs}
                    kwargs['rejected'][:] = [name for name in kwargs['rejected'] if name.replace('\\', '/') not in stubs]
                return {key.replace('\\', '/'): value for key, value in result.items()}

            tree.read_tree = read_tree
            tree._corecoder_posix_keys = True


def workspace(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and path.drive.lower() != 'd:'):
        raise ValueError('Use a fresh directory under project .tmp on D:')
    return path
