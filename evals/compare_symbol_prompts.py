"""Interleaved symbol-patch prompt comparison on an admitted development task."""

import argparse
import json
from pathlib import Path

from .compare_workflows import aggregate, schedule
from .real_admission import DATA
from .real_tasks import admitted_case, run_real
from .runner import implementation_metadata, write_summary
from .schema import RunConfig


def compare(admission, catalog, task_id, output, config, repeat=3):
    if config.mode != 'live' or config.search_backend != 'off' or config.search_history != 'full':
        raise ValueError('Comparison needs live/off/full as its base configuration')
    axis = 'symbol-prompt'
    configs = {'baseline': config, 'behavior-check': config}
    planned = list(schedule([task_id], repeat, tuple(configs)))
    inputs = admitted_case(admission, catalog, task_id)
    output = output.resolve()
    if output.is_relative_to(inputs[3].resolve()) or output.is_relative_to(inputs[2].resolve()):
        raise ValueError('Comparison output must stay outside admitted source and checks')
    output.mkdir(parents=True, exist_ok=False)
    source = implementation_metadata()
    freeze = {'axis': axis, 'implementation': source, 'case': inputs[0], 'checks_hash': inputs[1]['checks_hash'],
              'revisions': inputs[1]['revisions'], 'test_environment': inputs[4],
              'configs': {arm: value.to_dict() for arm, value in configs.items()},
              'schedule': [{'repetition': rep, 'arm': arm} for rep, _, arm in planned]}
    (output / 'freeze.json').write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = {arm: [] for arm in configs}
    state = {'axis': axis, 'completed': False, 'planned_runs': len(planned), 'stop_reason': None,
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
            report = run_real(*inputs, configs[arm], output / arm, workflow='symbol-patch', symbol_prompt_policy=arm)
            report.update(repetition=rep, comparison_arm=arm)
            rows[arm].append(report)
            persist()
            print(f"{rep} {arm}: {report['status']}", flush=True)
            unchanged()
            if report['implementation']['source_hash'] != source['source_hash']:
                raise ValueError('Run used a different implementation')
            if report['status'] in {'cancelled', 'infrastructure_error', 'agent_error'}:
                raise ValueError('Run did not complete the comparison protocol')
            workers = [row['worker'] for reports in rows.values() for row in reports]
            for key in ('evidence_hash', 'tool_schema_hash'):
                if len({worker.get(key) for worker in workers}) != 1 or workers[0].get(key) is None:
                    raise ValueError('Evidence or tool schema differs between comparison runs')
            for reports in rows.values():
                if not reports:
                    continue
                hashes = {row['worker'].get('protocol_prompt_hash') for row in reports}
                if None in hashes or len(hashes) != 1:
                    raise ValueError('Prompt changed within a comparison arm')
            digests = set()
            for worker in workers:
                for phase in ('ollama_before', 'ollama_after'):
                    metadata = worker.get(phase) or {}
                    models = metadata.get('identity', metadata.get('loaded', {})).get('models', [])
                    matches = [model['digest'] for model in models
                               if model.get('name') == config.model and model.get('digest')]
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
                       reasoning_effort='none', evidence_dependency_depth=1)
    state = compare(args.admission.resolve(), args.catalog, args.task, args.output, config, args.repeat)
    print(args.output.resolve() / 'comparison.json', flush=True)
    return 0 if state['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
