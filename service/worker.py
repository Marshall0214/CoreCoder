"""One trusted fixture task per isolated service process."""

import json
import os
import sys
from pathlib import Path

from evals.runner import DEFAULT_SUITE, run_task
from evals.schema import RunConfig, load_suite

SUITES = {'smoke': DEFAULT_SUITE, 'localization': DEFAULT_SUITE / 'localization-v1'}


def execute(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    if job['request'].get('workflow') == 'tentative-approval-v1':
        from service.tentative import run

        try:
            report = run(path, decision=job.get('approval'))
        except Exception as exc:  # noqa: BLE001 - expose failure class, never provider credentials
            report = {'status': 'service_execution_error', 'accepted': False,
                      'verification': {'passed': False}, 'failure_type': type(exc).__name__}
            snapshot_path = path.parent / 'workflow.json'
            if snapshot_path.is_file():
                snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
                snapshot.update(stage='failed', failure_type=type(exc).__name__)
                temporary = path.parent / 'workflow.tmp'
                temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(snapshot_path)
        (path.parent / 'result.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        return
    task = load_suite(SUITES[job['request']['suite']], [job['request']['task_id']])[0]
    config = RunConfig(mode=job['request']['mode'], model='qwen3.5:27b',
                       base_url=os.environ.get('CORECODER_MODEL_BASE_URL', 'http://localhost:11434/v1'), reasoning_effort='none',
                       search_backend=job['request']['search_backend'], token_budget=15000,
                       wall_timeout=180, test_timeout=15)
    if job['request'].get('workflow') == 'langgraph-approval-v1':
        from workflows.approval import run_approval_workflow

        report = run_approval_workflow(task, config, path.parent, decision=job.get('approval'))
    elif job['request'].get('workflow') == 'langgraph-v1':
        from workflows.repair import run_workflow

        report = run_workflow(task, config, path.parent)
    else:
        report = run_task(task, config, path.parent / 'runs')
    (path.parent / 'result.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    execute(Path(sys.argv[1]).resolve())
