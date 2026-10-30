"""Rebuild frozen request views offline; never infer, execute candidate code, or rescore."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.context_policy import request_breakdown
from repairflow.issue_agent import request_messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='Fresh D-drive output directory')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Require a fresh output directory under the project .tmp')
    packet = ROOT / 'docs/module_binding_20261029'
    source = packet / 'live'
    manifest = json.loads((ROOT / 'docs/module-binding-20261029.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if hashlib.sha256((packet / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen input changed: ' + name)
    report = json.loads((source / 'report.json').read_text(encoding='utf-8'))
    rows, projected = [], []
    for path in sorted(source.glob('step-*-messages.json')):
        original = json.loads(path.read_text(encoding='utf-8'))
        payload = json.loads(original[1]['content'])
        full = request_messages(payload, 'full')
        if full != original:
            raise ValueError('Full policy does not reproduce the frozen request: ' + path.name)
        compact = request_messages(payload, 'compact-v1')
        current = json.loads(compact[1]['content'])
        assert {k: v for k, v in current.items() if k != 'observations'} == {
            k: v for k, v in payload.items() if k != 'observations'}
        assert len(current['observations']) == len(payload['observations'])
        for old, new in zip(payload['observations'], current['observations']):
            for key in ('step', 'action', 'status', 'error', 'public_check_feedback', 'changed_files', 'net_changed_files'):
                assert old.get(key) == new.get(key), (path.name, key)
        before = request_breakdown(full, [])['request_estimate']
        after = request_breakdown(compact, [])['request_estimate']
        step = int(path.name.split('-')[1])
        rows.append({'step': step, 'provider_called_in_original': step <= report['fresh_model_calls'],
                     'full_request_estimate': before, 'compact_request_estimate': after,
                     'difference': after - before,
                     'frozen_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        projected.append((path.name, compact))
    called = [row for row in rows if row['provider_called_in_original']]
    before = sum(row['full_request_estimate'] for row in called)
    after = sum(row['compact_request_estimate'] for row in called)
    summary = {'scope': 'Same nine frozen request states; eight originally called. No new inference or scoring.',
               'called_request_count': len(called), 'request_states': len(rows),
               'full_called_request_estimate': before, 'compact_called_request_estimate': after,
               'estimated_change_percent': round((after / before - 1) * 100, 2),
               'preservation': 'Exact goals, public tests, source fragments, constraints, counters, errors and test feedback',
               'rows': rows,
               'limits': 'Heuristic request estimates, not actual saved tokens or proof of repair improvement.',
               'implementation_sha256': hashlib.sha256((ROOT / 'repairflow/issue_agent.py').read_bytes()).hexdigest()}
    output.mkdir(parents=True)
    for name, messages in projected:
        (output / name).write_text(json.dumps(messages, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
