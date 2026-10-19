"""Offline worker deliberately killed by the service to exercise Docker cleanup."""
import sys
import time
import uuid
from pathlib import Path

from sandbox import runner


def main():
    root = Path(sys.argv[1]).resolve().parent
    entry = root / 'runner.py'
    entry.write_text('pass', encoding='utf-8')
    name = 'corecoder-test-cancel-' + uuid.uuid4().hex
    try:
        runner.control(runner.command(runner.preflight()['image_id'], name, runner.owner(root),
                                      root, root, entry, '.', 'pkg', 'Target'))
        runner.control(['start', name])
        (root / 'sandbox-ready').touch()
        time.sleep(60)
    finally:
        runner.control(['rm', '-f', name])


if __name__ == '__main__':
    main()
