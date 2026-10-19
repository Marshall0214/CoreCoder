"""Prepare bundles and run the identical repair engine used by the local API."""
import argparse
import json
from pathlib import Path

from repairflow.bundles import export
from repairflow.engine import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--task', required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--include-replay', action='store_true')
    run = commands.add_parser('run')
    run.add_argument('--bundle', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--mode', choices=('live', 'replay'), required=True)
    demo = commands.add_parser('demo')
    demo.add_argument('--bundle', type=Path, required=True)
    demo.add_argument('--output', type=Path, required=True)
    issue = commands.add_parser('import-issue', help='Read-only GitHub import and Docker reproduction admission')
    issue.add_argument('--url', required=True)
    issue.add_argument('--config', type=Path, required=True, help='Administrator-owned trusted task configuration')
    issue.add_argument('--output', type=Path, required=True)
    repair_issue = commands.add_parser('repair-issue', help='Repair an admitted Issue; public checks only, manual review required')
    repair_issue.add_argument('--prepared', type=Path, required=True)
    repair_issue.add_argument('--config', type=Path, required=True, help='Original administrator-owned task configuration')
    repair_issue.add_argument('--output', type=Path, required=True)
    repair_issue.add_argument('--mode', choices=('scripted', 'ollama'), required=True)
    repair_issue.add_argument('--responses', type=Path, help='Scripted mode only: one or two JSON response strings')
    repair_issue.add_argument('--model', default='qwen3.5:27b', help='Installed local Ollama model; thinking is disabled')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(export(args.task, args.output, args.include_replay))
    elif args.command == 'demo':
        from repairflow.demo import run as run_demo

        print(json.dumps(run_demo(args.bundle, args.output), ensure_ascii=False))
    elif args.command == 'import-issue':
        from repairflow.github_issue import prepare as prepare_issue
        from sandbox.runner import SandboxError

        try:
            report = prepare_issue(args.url, args.config, args.output)
        except (SandboxError, ValueError, OSError) as exc:
            report = {'status': exc.status if isinstance(exc, SandboxError) else 'invalid_preparation_input',
                      'ready_for_repair': False, 'fresh_model_calls': 0}
        print(json.dumps({k: report[k] for k in ('status', 'ready_for_repair', 'fresh_model_calls')}, ensure_ascii=False))
        return 0 if report['ready_for_repair'] else 1
    elif args.command == 'repair-issue':
        from repairflow.issue_repair import execute as repair_prepared
        from sandbox.runner import SandboxError

        try:
            report = repair_prepared(args.prepared, args.config, args.output, mode=args.mode,
                                     responses=args.responses, model=args.model)
        except (SandboxError, ValueError, OSError, KeyError, TypeError) as exc:
            report = {'status': exc.status if isinstance(exc, SandboxError) else 'invalid_repair_input',
                      'public_checks_passed': False, 'accepted': False, 'fresh_model_calls': 0}
        print(json.dumps({k: report[k] for k in ('status', 'public_checks_passed', 'accepted', 'fresh_model_calls')},
                         ensure_ascii=False))
        return 0 if report['public_checks_passed'] else 1
    else:
        report = execute(args.bundle, args.mode, args.output)
        print(json.dumps({k: report[k] for k in ('status', 'accepted', 'execution_mode', 'fresh_model_calls', 'metrics')},
                         ensure_ascii=False))
        return 0 if report['accepted'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
