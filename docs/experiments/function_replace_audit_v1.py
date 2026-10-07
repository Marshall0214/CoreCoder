"""Resolve historical full-function candidates without new inference or scoring."""
import argparse
import json
from pathlib import Path

from docs.experiments import function_replace_v1 as replacement
from docs.experiments import patch_delta_compare_v1 as old

ROOT = old.ROOT


def run(output):
    output = output.resolve()
    if output.exists():
        raise ValueError('Use a fresh output directory')
    rows = []
    record = ROOT/'.tmp/real-defects/patch-delta-compare-v1'
    for name in old.public.TARGETS:
        history = record/name/'baseline'
        workspace = history/'public-candidate/source'
        final = history/'public-final/source'
        context = json.loads((history/'feedback-context.json').read_text(encoding='utf-8'))['evidence']
        result = json.loads((history/'worker-result.json').read_text(encoding='utf-8'))
        keys = result['stages'][1]['edited_symbols']
        index = old.worker.retention.functions.FunctionIndex(final, [r['path'] for r in context])
        index.refresh()
        edits = []
        for key in keys:
            row = next(r for r in context if r['path'] == key['path'] and r['symbol'] == key['symbol'])
            a, b, _ = index.parsed[row['path']]['symbols'][row['symbol']]
            new = ''.join(index.parsed[row['path']]['lines'][a-1:b])
            edits.append({'file': row['path'], 'symbol': row['symbol'], 'content_hash': row['content_hash'], 'new': new})
        before = replacement.guard.files(workspace)
        patch = replacement.lower(json.dumps({'edits': edits}), workspace,
                                  [r['path'] for r in context], context)
        assert replacement.guard.files(workspace) == before
        assert len(json.loads(patch)['edits']) == len(keys)
        rows.append({'task_id': name, 'resolved_symbols': keys, 'source_unchanged': True})
    paths = [Path(__file__), Path(replacement.__file__), ROOT/'docs/experiments/function_replace_worker_v1.py']
    report = {'complete': True, 'model_calls': 0, 'private_grader_calls': 0, 'tasks': rows,
              'source_record_sha256': old.repair.audit.sha(record/'experiment.json'),
              'adapter_hashes': {p.relative_to(ROOT).as_posix(): old.repair.audit.sha(p) for p in paths}}
    output.mkdir(parents=True)
    (output/'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'complete': True, 'model_calls': 0, 'resolved_functions': sum(len(r['resolved_symbols']) for r in rows)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
