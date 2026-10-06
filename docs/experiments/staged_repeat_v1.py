"""Run the frozen development-only repeat experiment without changing the repair engine."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.real_admission import DATA
from evals.real_suite import file_hash, load_manifest, prepare, run_suite
from evals.runner import implementation_metadata
from evals.schema import RunConfig
from evals.worker import ollama_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    admissions = {}
    for item in args.admission:
        name, separator, path = item.partition('=')
        if not separator or not path or name in admissions:
            parser.error('Admissions must be unique SOURCE=PATH entries')
        admissions[name] = Path(path).resolve()
    protocol_path = DATA / 'staged-repeat-v1.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    if (protocol['purpose'] != 'development-staged-repeat-diagnosis' or protocol['repeat'] != 3
            or protocol['expected_runs'] != 42 or protocol['prior_pilot_included']):
        raise ValueError('Expected the frozen three-repeat development protocol')
    expected = {(rep, workflow) for rep in range(1, 4) for workflow in ('agent-loop', 'staged')}
    order = [tuple(block) for block in protocol['block_order']]
    if len(order) != 6 or set(order) != expected:
        raise ValueError('Each repetition must contain both workflows exactly once')
    manifests, profiles, tasks = {}, {}, {}
    for workflow in ('agent-loop', 'staged'):
        record = protocol['profiles'][workflow]
        path = DATA / record['manifest']
        if path.parent != DATA or file_hash(path) != record['sha256']:
            raise ValueError('Frozen manifest changed')
        data, entries = load_manifest(path)
        if data['workflow'] != workflow:
            raise ValueError('Manifest workflow mismatch')
        manifests[workflow], profiles[workflow], tasks[workflow] = path, data, entries
    if profiles['agent-loop']['config'] != profiles['staged']['config'] or tasks['agent-loop'] != tasks['staged']:
        raise ValueError('Both workflows must share tasks and configured total budgets')
    if len(tasks['staged']) != 7:
        raise ValueError('Expected seven development tasks')
    prepared = prepare(tasks['staged'], admissions)
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(path.resolve()) for case in prepared for path in case[2:4]):
        raise ValueError('Use a new output directory outside admitted source and checks')
    config = RunConfig(**profiles['staged']['config'])

    def check_identity():
        if implementation_metadata()['source_hash'] != protocol['implementation_sha256']:
            raise ValueError('Repair implementation changed; version the experiment')
        metadata = ollama_metadata(config) or {}
        models = metadata.get('identity', {}).get('models', [])
        if not any(row['name'] == config.model and row['digest'] == protocol['model_digest'] for row in models):
            raise ValueError('Frozen local model digest unavailable or changed')

    check_identity()
    if args.validate_only:
        print('Validated: 7 tasks x 2 workflows x 3 repetitions; no repair model calls')
        return 0
    output.mkdir(parents=True, exist_ok=False)
    report = {'protocol': protocol, 'protocol_sha256': file_hash(protocol_path), 'complete': False,
              'completed_runs': 0, 'expected_runs': 42, 'blocks': [], 'benchmark_eligible': False}

    def save():
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for repetition, workflow in order:
        check_identity()
        block = output / f'repeat-{repetition}-{workflow}'
        print(f'Starting repetition {repetition}: {workflow}', flush=True)
        suite = run_suite(manifests[workflow], admissions, block, 'live', repeat=1)
        report['blocks'].append({'repetition': repetition, 'workflow': workflow,
                                 'report': str(block / 'suite-report.json'), 'complete': suite['complete'],
                                 'completed_runs': len(suite['runs'])})
        report['completed_runs'] += len(suite['runs'])
        save()
        if not suite['complete']:
            return 1
    check_identity()
    report['complete'] = report['completed_runs'] == report['expected_runs']
    save()
    print(output / 'experiment.json', flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
