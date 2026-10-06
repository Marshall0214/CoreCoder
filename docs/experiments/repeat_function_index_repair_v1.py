"""Repeat the unchanged frozen line/function repair protocol and summarize pairs."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from docs.experiments import function_index_repair_v1 as repair

EVIDENCE_SHA = '6380da2dcc0d0b64ff5f48c30cb1c380ef4476cd6a78008407687f123eaf3145'


def aggregate(runs, tasks, repeats):
    keyed = {}
    for row in runs:
        key = (row['repeat'], row['task_id'], row['policy'])
        if key in keyed or row['task_id'] not in tasks or row['policy'] not in repair.POLICIES or not 1 <= row['repeat'] <= repeats:
            raise ValueError('Duplicate or unexpected repeated branch')
        keyed[key] = row
    paired = Counter()
    per_task = []
    for task in tasks:
        for number in range(1, repeats + 1):
            left, right = (keyed.get((number, task, p)) for p in repair.POLICIES)
            if left is None or right is None:
                paired['incomplete'] += 1
            else:
                paired[['both_failed', 'function_only', 'line_only', 'both_passed'][2 * bool(left['accepted']) + bool(right['accepted'])]] += 1
        groups = {}
        for policy in repair.POLICIES:
            rows = [keyed[(n, task, policy)] for n in range(1, repeats + 1) if (n, task, policy) in keyed]
            prompts = {r['worker'].get('prompt_hash') for r in rows}
            groups[policy] = {'runs': len(rows), 'passed': sum(r['accepted'] for r in rows),
                              'statuses': dict(Counter(r['status'] for r in rows)),
                              'status_consistent': len(rows) == repeats and len({r['status'] for r in rows}) == 1,
                              'prompt_identical': len(rows) == repeats and None not in prompts and len(prompts) == 1}
        per_task.append({'task_id': task, 'policies': groups})
    return {'complete': len(keyed) == len(tasks) * repeats * 2,
            'unique_tasks': len(tasks), 'expected_runs': len(tasks) * repeats * 2,
            'summary': repair.summarize(runs), 'paired': dict(paired), 'per_task': per_task,
            'per_repeat': [{'repeat': n, 'summary': repair.summarize([r for r in runs if r['repeat'] == n])}
                           for n in range(1, repeats + 1)]}


def run(source, output, repeats=3):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError('Repeat count must be an integer from 1 to 10')
    cases, bundles = repair.prepare(source, output)
    # Preserve the original Windows JSON file bytes; source text remains JSON-escaped.
    encoded = json.dumps(bundles, ensure_ascii=False, indent=2).encode('utf-8').replace(b'\n', b'\r\n')
    if hashlib.sha256(encoded).hexdigest() != EVIDENCE_SHA:
        raise ValueError('Evidence differs from the original paired experiment')
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    (output / 'evidence.json').write_bytes(encoded)
    paths = [Path(__file__), Path(repair.__file__), Path(repair.patcher.__file__), Path(repair.audit.__file__)]
    hashes = {p.relative_to(repair.audit.ROOT).as_posix(): repair.audit.sha(p) for p in paths}
    protocol = {'protocol': 'function-index-repair-repeat-v1', 'development_only': True,
                'benchmark_eligible': False, 'repeats': repeats, 'expected_runs': len(cases) * 2 * repeats,
                'tasks': [c['task_id'] for c in cases], 'observations_sha256': repair.OBS_SHA,
                'evidence_sha256': EVIDENCE_SHA, 'engine_hash': repair.audit.ENGINE,
                'repair_model_digest': repair.MODEL_DIGEST, 'config': repair.config().to_dict(),
                'adapter_hashes': hashes, 'prior_runs_included': False,
                'order': 'repeat-major; unchanged alternating task policy order in every repeat',
                'limitations': 'repeated calls on seven development cases; not independent tasks or held-out evidence'}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    runs = []

    def save():
        report = aggregate(runs, protocol['tasks'], repeats)
        report.update(protocol=protocol, runs=runs)
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        return report

    save()
    for number in range(1, repeats + 1):
        if repair.audit.sha(output / 'evidence.json') != EVIDENCE_SHA or any(
                repair.audit.sha(repair.audit.ROOT / name) != value for name, value in hashes.items()):
            raise ValueError('Frozen repeat evidence or adapter changed')
        child = output / f'repeat-{number:02d}'
        print(f'Repeat {number}/{repeats}', flush=True)
        try:
            repair.run(source, child)
        finally:
            # Preserve partial calls and failures when a child stops; never mark them complete.
            path = child / 'experiment.json'
            if path.exists():
                data = json.loads(path.read_text(encoding='utf-8'))
                if data['protocol']['evidence_sha256'] != EVIDENCE_SHA or data['protocol']['config'] != protocol['config']:
                    raise ValueError('Repeated child protocol differs')
                runs.extend(dict(r, repeat=number) for r in data['runs'])
            save()
    repair.check_identity(repair.config())
    report = save()
    if not report['complete']:
        raise ValueError('Repeated experiment is incomplete')
    print(json.dumps({'summary': report['summary'], 'paired': report['paired']}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve(), args.repeat)


if __name__ == '__main__':
    main()
