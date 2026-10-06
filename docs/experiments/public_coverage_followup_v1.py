"""Offline public-identifier coverage for definition pilot and cross-file baseline."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docs.experiments.staged_evidence_coverage_v1 import covered_lines, diagnose
from evals.real_suite import file_hash
from evals.schema import RunConfig, relative_path
from evals.staged_repair import select_evidence, validate_localization

PROTOCOL_PATH = Path(__file__).with_suffix('.json')


def missing_ranges(start, end, present):
    missing, begin = [], None
    for line in range(start, end + 2):
        if line <= end and line not in present:
            if begin is None:
                begin = line
        elif begin is not None:
            missing.append([begin, line - 1])
            begin = None
    return missing


def coverage(description, sources, pool, limit, bare_names=()):
    result = diagnose(description, sources, pool, limit, 'read-first', bare_names)
    candidates = pool['reads'] + pool['seeds']
    selected = select_evidence(pool['reads'], pool['seeds'], limit)
    for anchor in result['anchors']:
        path, start, end = anchor['path'], anchor['start_line'], anchor['end_line']
        anchor['read_missing_ranges'] = missing_ranges(start, end, covered_lines(pool['reads'], path))
        anchor['pool_missing_ranges'] = missing_ranges(start, end, covered_lines(candidates, path))
        anchor['visible_missing_ranges'] = missing_ranges(start, end, covered_lines(selected, path))
        stages = []
        if anchor['pool_lines'] < anchor['span_lines']:
            stages.append('acquisition')
        if anchor['selection_lost_lines']:
            stages.append('packing')
        anchor['gap_stages'] = stages
        anchor['gap_stage'] = 'mixed' if len(stages) == 2 else stages[0] if stages else 'none'
    result['definition_anchors'] = [a for a in result['anchors'] if a['kind'] == 'definition']
    result['limitations'] = ('Exact public-name coverage is a lexical diagnostic, not necessary repair locations '
                            'or semantic completeness. No definition anchors does not mean no dependencies.')
    return result


def run(protocol):
    for name, expected in protocol['frozen_files'].items():
        if file_hash(ROOT / relative_path(name)) != expected:
            raise ValueError('Frozen audit input or adapter changed')
    rows = []
    for record in protocol['cases']:
        checkpoint_path = ROOT / relative_path(record['checkpoint'])
        checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        workspace = ROOT / relative_path(record['workspace'])
        config = RunConfig(**checkpoint['config'])
        validate_localization(checkpoint, workspace, record['description'], checkpoint['allowed_files'], config)
        sources = {name: (workspace / relative_path(name)).read_text(encoding='utf-8') for name in checkpoint['allowed_files']}
        result = coverage(record['description'], sources, checkpoint['pool'], config.search_max_chars, record['bare_names'])
        if record.get('patch_request'):
            request = json.loads((ROOT / relative_path(record['patch_request'])).read_text(encoding='utf-8'))
            payload = json.loads(request[1]['content'])
            expected = select_evidence(checkpoint['pool']['reads'], checkpoint['pool']['seeds'], config.search_max_chars)
            if payload['description'] != record['description'] or payload['fragments'] != expected:
                raise ValueError('Audit selection differs from actual patch input')
        rows.append({'label': record['label'], 'task_id': record['task_id'], 'checkpoint_sha256': file_hash(checkpoint_path),
                     'description': record['description'], 'bare_names': record['bare_names'], 'coverage': result})
    return {'purpose': 'offline-public-coverage-followup-v1', 'benchmark_eligible': False, 'model_calls': 0,
            'protocol_sha256': file_hash(PROTOCOL_PATH), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    if protocol['purpose'] != 'offline-public-coverage-followup-v1':
        raise ValueError('Unexpected protocol')
    output = args.output.resolve()
    protected = [ROOT / relative_path(r['workspace']) for r in protocol['cases']]
    protected += [(ROOT / relative_path(n)).parent for n in protocol['frozen_files']]
    if output.exists() or any(output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in protected):
        raise ValueError('Use fresh output outside source and frozen inputs')
    result = run(protocol)
    output.mkdir(parents=True)
    (output / 'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in result['cases']:
        print(row['label'], row['coverage']['summary'])
    print(output / 'coverage.json')


if __name__ == '__main__':
    main()
