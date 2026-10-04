"""Run with python -m evals. Only live and fixed-evidence call a real model."""

import argparse
from pathlib import Path

from .runner import DEFAULT_SUITE, run_task, write_summary
from .schema import RunConfig, load_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--task", action="append", help="Task ID; repeat flag to select several")
    parser.add_argument("--mode", choices=("unchanged", "reference", "scripted", "live", "fixed-evidence"), default="unchanged")
    parser.add_argument("--output", type=Path, default=Path(".tmp/evals"))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--max-rounds", type=int, default=12)
    parser.add_argument("--token-budget", type=int, default=30000)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--context-tokens", type=int, default=16000)
    parser.add_argument("--wall-timeout", type=int, default=180)
    parser.add_argument("--test-timeout", type=int, default=15)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--search-backend", choices=("off", "none", "keyword"), default="off")
    parser.add_argument("--search-max-chars", type=int, default=6000)
    parser.add_argument("--search-history", choices=("full", "deduplicate"), default="full")
    parser.add_argument("--context-policy", choices=("none", "read-cover"), default="none")
    parser.add_argument("--prompt-policy", choices=("baseline", "contract-check"), default="baseline")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    try:
        config = RunConfig(**{key: getattr(args, key) for key in (
            "mode", "model", "base_url", "max_rounds", "token_budget", "max_output_tokens", "context_tokens",
            "wall_timeout", "test_timeout", "reasoning_effort", "temperature", "search_backend", "search_max_chars",
            "search_history", "context_policy", "prompt_policy")})
        tasks = load_suite(args.suite, args.task)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if config.mode in {"live", "fixed-evidence"}:
        from corecoder.config import _load_dotenv

        _load_dotenv()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for repetition in range(1, args.repeat + 1):
        for task in tasks:
            report = run_task(task, config, output, repetition)
            reports.append(report)
            print(f"{task.task_id}: {report['status']}", flush=True)
            if report["status"] == "cancelled":
                print(write_summary(reports, output))
                return 130
    print(write_summary(reports, output))
    return 0 if all(r["accepted"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
