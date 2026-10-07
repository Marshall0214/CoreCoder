"""Real interrupt/checkpoint flow with a slow execution for cancellation/crash tests."""

import json
import sys
from pathlib import Path

from evals.schema import RunConfig, load_suite
from service.worker import SUITES
from tests.service_worker_stub import main as delayed_worker
from workflows.approval import run_approval_workflow

if __name__ == '__main__':
    path = Path(sys.argv[1])
    job = json.loads(path.read_text(encoding='utf-8'))
    task = load_suite(SUITES[job['request']['suite']], [job['request']['task_id']])[0]

    def execute(*args):
        delayed_worker()
        return {'status': 'passed', 'accepted': True, 'verification': {'passed': True}}

    report = run_approval_workflow(task, RunConfig(mode=job['request']['mode']), path.parent,
                                   decision=job.get('approval'), execute=execute)
    (path.parent / 'result.json').write_text(json.dumps(report), encoding='utf-8')
