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
    args = parser.parse_args()
    if args.command == 'prepare':
        print(export(args.task, args.output, args.include_replay))
    elif args.command == 'demo':
        from repairflow.demo import run as run_demo

        print(json.dumps(run_demo(args.bundle, args.output), ensure_ascii=False))
    else:
        report = execute(args.bundle, args.mode, args.output)
        print(json.dumps({k: report[k] for k in ('status', 'accepted', 'execution_mode', 'fresh_model_calls', 'metrics')},
                         ensure_ascii=False))
        return 0 if report['accepted'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
