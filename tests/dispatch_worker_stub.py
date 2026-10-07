"""Select the real approval graph or legacy lifecycle stub for acceptance only."""

import json
import runpy
import sys
from pathlib import Path

if __name__ == '__main__':
    job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    module = ('tests.approval_worker_stub' if job['request'].get('workflow') == 'langgraph-approval-v1'
              else 'tests.service_worker_stub')
    runpy.run_module(module, run_name='__main__', alter_sys=True)
