"""One trusted fixture task per isolated service process."""

import json
import sys
from pathlib import Path

from evals.runner import DEFAULT_SUITE, run_task
from evals.schema import RunConfig, load_suite

SUITES = {'smoke': DEFAULT_SUITE, 'localization': DEFAULT_SUITE / 'localization-v1'}


def execute(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    task = load_suite(SUITES[job['request']['suite']], [job['request']['task_id']])[0]
    config = RunConfig(mode=job['request']['mode'], model='qwen3.5:27b',
                       base_url='http://localhost:11434/v1', reasoning_effort='none',
                       search_backend=job['request']['search_backend'], token_budget=15000,
                       wall_timeout=180, test_timeout=15)
    report = run_task(task, config, path.parent / 'runs')
    (path.parent / 'result.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    execute(Path(sys.argv[1]).resolve())
