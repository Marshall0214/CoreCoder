"""Reproduce the frozen v5/v6 event check comparison from the repository root."""

import argparse
from dataclasses import replace
from pathlib import Path

from evals.compare_workflows import run_comparison
from evals.schema import RunConfig, load_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New experiment directory')
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    config = RunConfig(mode='contract-feedback', model='qwen3.5:27b',
                       base_url='http://localhost:11434/v1', reasoning_effort='none',
                       search_backend='keyword', evidence_order='path',
                       patch_policy='contract-coverage', public_check_policy='contract-surface')
    tasks = load_suite(Path(__file__).resolve().parents[2] / 'evals/fixtures/localization-v1', ['event-replay'])
    result = run_comparison(tasks, {'v5-surface': config,
                                   'v6-scenarios': replace(config, public_check_policy='contract-scenarios')},
                            args.output, repeat=args.repeat)
    return 0 if result['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
