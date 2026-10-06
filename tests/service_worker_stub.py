"""Controllable real subprocess used only by service lifecycle integration tests."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    path = Path(sys.argv[1])
    job = json.loads(path.read_text())
    mode = job['request']['mode']
    if mode == 'unchanged':
        kwargs = {'start_new_session': True} if os.name != 'nt' else {}
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        (path.parent / 'pids.json').write_text(json.dumps([os.getpid(), child.pid]))
        time.sleep(60)
    elif mode == 'live':
        raise SystemExit(3)
    else:
        result = {'status': 'passed', 'accepted': True, 'verification': {'passed': mode != 'reference'}}
        (path.parent / 'result.json').write_text(json.dumps(result))


if __name__ == '__main__':
    main()
