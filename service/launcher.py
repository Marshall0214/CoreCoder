"""Do not execute a worker before its process identity has been persisted."""

import json
import os
import runpy
import sys
import time
from pathlib import Path

import psutil


def await_approval(path, timeout=10):
    identity = {'pid': os.getpid(), 'process_started_at': psutil.Process().create_time()}
    temporary = path.parent / 'worker-identity.tmp'
    temporary.write_text(json.dumps(identity), encoding='utf-8')
    temporary.replace(path.parent / 'worker-identity.json')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (path.parent / 'start-approved').is_file():
            return True
        time.sleep(0.02)
    return False


def main():
    module, path = sys.argv[1], Path(sys.argv[2])
    if not await_approval(path):
        raise SystemExit(3)
    sys.argv = [module, str(path)]
    runpy.run_module(module, run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
