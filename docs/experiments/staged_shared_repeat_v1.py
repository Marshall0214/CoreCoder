"""Repeat patch branches on frozen localization checkpoints, without new localization calls."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from corecoder.config import _load_dotenv
from evals.real_admission import DATA
from evals.real_suite import file_hash, load_manifest, prepare
from evals.real_tasks import run_real
from evals.runner import implementation_metadata
from evals.schema import RunConfig, relative_path
from evals.staged_repair import validate_localization
from evals.worker import ollama_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    admissions = {}
    for item in args.admission:
        name, separator, value = item.partition('=')
        if not separator or not value or name in admissions:
            parser.error('Admissions must be unique SOURCE=PATH entries')
        admissions[name] = Path(value).resolve()
    protocol_path = DATA / 'staged-shared-repeat-v1.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    manifest = DATA / relative_path(protocol['manifest'])
    if (protocol['schema_version'] != 1 or protocol['purpose'] != 'development-frozen-checkpoint-repeat-v1'
            or protocol['repeat'] != 3 or protocol['expected_patch_runs'] != 42
            or protocol['expected_new_localizations'] != 0 or protocol['historical_patch_runs_included']
            or file_hash(manifest) != protocol['manifest_sha256']):
        raise ValueError('Expected the frozen three-repeat patch protocol')
    data, entries = load_manifest(manifest)
    prepared = prepare(entries, admissions)
    cases = {case[0]['case_id']: case for case in prepared}
    if len(cases) != 7 or data['workflow'] != 'staged' or set(protocol['checkpoints']) != set(cases):
        raise ValueError('Expected exactly seven staged development checkpoints')
    order = protocol['order']
    if (len(order) != 21 or {(row['repetition'], row['task_id']) for row in order}
            != {(rep, task) for rep in range(1, 4) for task in cases}
            or any(len(row['policies']) != 2 or set(row['policies']) != {'read-first', 'seed-first'} for row in order)):
        raise ValueError('Each task must have both policies in each repetition')
    config = RunConfig(**data['config'])
    paths = {}
    for task, case in cases.items():
        record = protocol['checkpoints'][task]
        path = ROOT / relative_path(record['path'])
        if not path.resolve().is_relative_to(ROOT) or file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint file changed or unavailable')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        if (checkpoint['checkpoint_hash'] != record['checkpoint_hash']
                or checkpoint['localization_result']['candidate_pool_hash'] != record['candidate_pool_hash']
                or checkpoint['metrics']['budget_accounted_tokens'] != record['shared_tokens']):
            raise ValueError('Checkpoint identity or shared cost mismatch')
        validate_localization(checkpoint, case[3] / 'before', case[0]['public_problem'],
                              checkpoint['allowed_files'], config)
        paths[task] = path
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(p.resolve()) for case in prepared for p in case[2:4]):
        raise ValueError('Use a fresh output directory outside admitted source and checks')
    _load_dotenv()

    def check_identity():
        if implementation_metadata()['source_hash'] != protocol['implementation_sha256']:
            raise ValueError('Repair implementation changed; version the experiment')
        models = (ollama_metadata(config) or {}).get('identity', {}).get('models', [])
        if not any(m['name'] == config.model and m['digest'] == protocol['model_digest'] for m in models):
            raise ValueError('Frozen local model unavailable or changed')

    check_identity()
    if args.validate_only:
        print('Validated: 7 frozen checkpoints, 42 patch branches, zero new localization calls')
        return 0
    output.mkdir(parents=True, exist_ok=False)
    report = {'protocol': protocol, 'protocol_sha256': file_hash(protocol_path), 'benchmark_eligible': False,
              'complete': False, 'new_localizations': 0, 'expected_patch_runs': 42, 'patch_runs': []}

    def save():
        report['completed_patch_runs'] = len(report['patch_runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for block in order:
        check_identity()
        task, repetition = block['task_id'], block['repetition']
        for policy in block['policies']:
            if file_hash(paths[task]) != protocol['checkpoints'][task]['sha256']:
                raise ValueError('Frozen checkpoint changed between branches')
            row = run_real(*cases[task], config, output / f'repeat-{repetition}' / policy,
                           workflow='staged-replay', staged_evidence_policy=policy,
                           localization_checkpoint=paths[task])
            row['repetition'] = repetition
            report['patch_runs'].append(row)
            save()
            print(f'{repetition}/3 {task} {policy}: {row["status"]}', flush=True)
            if row['status'] == 'cancelled':
                return 1
    check_identity()
    for task, path in paths.items():
        if file_hash(path) != protocol['checkpoints'][task]['sha256']:
            raise ValueError('Frozen checkpoint changed during experiment')
    report['complete'] = len(report['patch_runs']) == 42
    save()
    print(output / 'experiment.json', flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
