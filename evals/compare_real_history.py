"""Interleaved full/deduplicated search history on one admitted real development task."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .compare_workflows import aggregate, schedule
from .real_admission import DATA
from .real_tasks import admitted_case, run_real
from .runner import implementation_metadata, write_summary
from .schema import RunConfig


def trace_metrics(report):
    records = [json.loads(line) for line in (Path(report['artifacts']) / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    searches = [record for record in records if record['event'] == 'search_completed']
    tools = [record for record in records if record['event'] == 'tool_started']
    return {'search_calls': len(searches), 'reference_hits': sum(row.get('reference_hits', 0) for row in searches),
            'omitted_chars': sum(row.get('omitted_chars', 0) for row in searches),
            'edit_calls': sum(row['tool'] in {'edit_file', 'write_file'} for row in tools),
            'visible_test_calls': sum(row['tool'] == 'bash' for row in tools),
            'changed_files': (report.get('verification') or {}).get('changed_files', []),
            'budget_blocks': [row for row in records if row['event'] == 'budget_blocked']}


def compare(admission, catalog, task_id, output, config, repeat=3):
    if config.mode != 'live' or config.search_backend != 'keyword' or config.search_history != 'full':
        raise ValueError('Comparison needs live keyword/full as its base configuration')
    inputs = admitted_case(admission, catalog, task_id)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = implementation_metadata()
    configs = {'full': config, 'deduplicate': replace(config, search_history='deduplicate')}
    planned = list(schedule([task_id], repeat, tuple(configs)))
    freeze = {'implementation': source, 'case': inputs[0], 'checks_hash': inputs[1]['checks_hash'],
              'revisions': inputs[1]['revisions'], 'test_environment': inputs[4],
              'configs': {arm: value.to_dict() for arm, value in configs.items()},
              'schedule': [{'repetition': rep, 'arm': arm} for rep, _, arm in planned]}
    (output / 'freeze.json').write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = {arm: [] for arm in configs}
    state = {'completed': False, 'planned_runs': len(planned), 'stop_reason': None,
             'scope': 'single real development task; not held-out performance', 'benchmark_eligible': False}

    def unchanged():
        current = implementation_metadata()
        if current['source_hash'] != source['source_hash'] or current['dependencies'] != source['dependencies']:
            raise ValueError('Frozen implementation or dependencies changed')
        admitted_case(admission, catalog, task_id)

    def persist():
        state['arms'] = {arm: aggregate(reports) for arm, reports in rows.items()}
        state['reports'] = rows
        (output / 'comparison.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        for rep, _, arm in planned:
            unchanged()
            report = run_real(*inputs, configs[arm], output / arm)
            report.update(repetition=rep, comparison_arm=arm, trace_metrics=trace_metrics(report))
            rows[arm].append(report)
            persist()
            print(f"{rep} {arm}: {report['status']}", flush=True)
            unchanged()
            if report['implementation']['source_hash'] != source['source_hash']:
                raise ValueError('Run used a different implementation')
            if report['status'] in {'cancelled', 'infrastructure_error', 'agent_error'}:
                raise ValueError('Run did not complete the comparison protocol')
            workers = [row['worker'] for reports in rows.values() for row in reports]
            for key in ('protocol_prompt_hash', 'tool_schema_hash'):
                if len({worker.get(key) for worker in workers}) != 1 or workers[0].get(key) is None:
                    raise ValueError('Prompt or tool schema differs between comparison runs')
            digests = set()
            for worker in workers:
                for phase in ('ollama_before', 'ollama_after'):
                    loaded = (worker.get(phase) or {}).get('loaded', {}).get('models', [])
                    matches = [model['digest'] for model in loaded if model.get('name') == config.model]
                    if len(matches) != 1:
                        raise ValueError('Local model digest unavailable; comparison cannot confirm a fixed model')
                    digests.update(matches)
            if len(digests) != 1:
                raise ValueError('Local model changed during comparison')
            state['model_digest'] = next(iter(digests))
        state['completed'] = True
    except KeyboardInterrupt:
        state['stop_reason'] = 'cancelled'
    except Exception as exc:  # noqa: BLE001 - preserve incomplete comparison evidence
        state['stop_reason'] = f'{type(exc).__name__}: {exc}'
    finally:
        for arm, reports in rows.items():
            if reports:
                write_summary(reports, output / arm)
        persist()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DATA / 'crossfile-candidates.json')
    parser.add_argument('--task', default='click-flag-envvar')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    from corecoder.config import _load_dotenv

    _load_dotenv()
    config = RunConfig(mode='live', model='qwen3.5:27b', base_url='http://localhost:11434/v1',
                       reasoning_effort='none', search_backend='keyword')
    state = compare(args.admission.resolve(), args.catalog, args.task, args.output, config, args.repeat)
    print(args.output.resolve() / 'comparison.json', flush=True)
    return 0 if state['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
