"""One read-only localization per task, two independently graded patch branches."""

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
    path = DATA / 'staged-shared-replay-v1.json'
    protocol = json.loads(path.read_text(encoding='utf-8'))
    manifest = DATA / protocol['manifest']
    if (protocol['purpose'] != 'development-shared-localization-replay-v1'
            or protocol['schema_version'] != 1 or protocol['expected_localizations'] != 7
            or protocol['expected_patch_runs'] != 14 or file_hash(manifest) != protocol['manifest_sha256']):
        raise ValueError('Shared replay protocol or manifest changed')
    data, entries = load_manifest(manifest)
    if data['workflow'] != 'staged' or len(entries) != 7:
        raise ValueError('Expected seven staged development tasks')
    prepared = prepare(entries, admissions)
    orders = protocol['policy_order_by_task']
    if set(orders) != {case[0]['case_id'] for case in prepared} or any(
            len(order) != 2 or set(order) != {'read-first', 'seed-first'} for order in orders.values()):
        raise ValueError('Each task must have both policies exactly once')
    config = RunConfig(**data['config'])
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(p.resolve()) for case in prepared for p in case[2:4]):
        raise ValueError('Use a fresh output directory outside admitted source and checks')
    _load_dotenv()

    def check_identity():
        if implementation_metadata()['source_hash'] != protocol['implementation_sha256']:
            raise ValueError('Implementation changed; version the replay protocol')
        models = (ollama_metadata(config) or {}).get('identity', {}).get('models', [])
        if not any(m['name'] == config.model and m['digest'] == protocol['model_digest'] for m in models):
            raise ValueError('Frozen local model unavailable or changed')

    check_identity()
    if args.validate_only:
        print('Validated: 7 shared localizations and 14 patch branches; no repair model calls')
        return 0
    output.mkdir(parents=True, exist_ok=False)
    report = {'protocol': protocol, 'protocol_sha256': file_hash(path), 'benchmark_eligible': False,
              'complete': False, 'localizations': [], 'patch_runs': []}

    def save():
        report['completed_localizations'] = len(report['localizations'])
        report['completed_patch_runs'] = len(report['patch_runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for case in prepared:
        check_identity()
        task = case[0]['case_id']
        local = run_real(*case, config, output / 'localizations', workflow='staged-localize')
        report['localizations'].append(local)
        save()
        print(f'{task} localization: {local["status"]}', flush=True)
        ready = (local['status'] == 'localized' and not local['verification']['changed_files']
                 and not local['verification']['scope_violations'])
        checkpoint = Path(local['artifacts']) / 'localization-checkpoint.json'
        checkpoint_hash = file_hash(checkpoint) if ready else None
        for policy in orders[task]:
            if local['status'] == 'cancelled':
                return 1
            if ready:
                if file_hash(checkpoint) != checkpoint_hash:
                    raise ValueError('Shared checkpoint changed between branches')
                row = run_real(*case, config, output / policy, workflow='staged-replay',
                               staged_evidence_policy=policy, localization_checkpoint=checkpoint)
            else:
                row = {'task_id': task, 'status': 'blocked_by_localization', 'accepted': False, 'metrics': None}
            row['staged_evidence_policy'] = policy
            report['patch_runs'].append(row)
            save()
            print(f'{task} {policy}: {row["status"]}', flush=True)
            if row['status'] == 'cancelled':
                return 1
        if ready and file_hash(checkpoint) != checkpoint_hash:
            raise ValueError('Shared checkpoint changed during patch execution')
    check_identity()
    report['complete'] = len(report['localizations']) == 7 and len(report['patch_runs']) == 14
    save()
    print(output / 'experiment.json', flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
