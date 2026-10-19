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
    else:
        report = execute(args.bundle, args.mode, args.output)
        print(json.dumps({k: report[k] for k in ('status', 'accepted', 'execution_mode', 'fresh_model_calls', 'metrics')},
                         ensure_ascii=False))
        return 0 if report['accepted'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
