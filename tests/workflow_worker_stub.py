"""Long-running graph adapter for actual process cancellation tests only."""

import json
import sys
from pathlib import Path

from evals.schema import RunConfig, load_suite
from service.worker import SUITES
from tests.service_worker_stub import main as delayed_worker
from workflows.repair import run_workflow


def main():
    path = Path(sys.argv[1])
    request = json.loads(path.read_text(encoding='utf-8'))['request']
    task = load_suite(SUITES[request['suite']], [request['task_id']])[0]

    def execute(task, config, output):
        delayed_worker()
        return {'status': 'passed', 'accepted': True, 'verification': {'passed': True}}

    run_workflow(task, RunConfig(mode=request['mode']), path.parent, execute=execute)


if __name__ == '__main__':
    main()
