"""Offline read-first containment deduplication preserving whole source fragments."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.real_admission import DATA
from evals.real_suite import file_hash, load_manifest
from evals.runtime import request_breakdown
from evals.schema import RunConfig, relative_path
from evals.staged_repair import object_hash, select_evidence, validate_localization
from evals.symbol_patch import SYMBOL_SYSTEM


def containment_evidence(reads, seeds, max_chars):
    """Skip exact baseline duplicates or candidates contained in one selected fragment."""
    if type(max_chars) is not int or max_chars < 0:
        raise ValueError('Expected a nonnegative integer character cap')
    rows = reads + seeds
    versions = {}
    for row in rows:
        start, end = row['start_line'], row['end_line']
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end
                or not isinstance(row['content'], str)
                or end - start + 1 not in {len(row['content'].splitlines()),
                                          len(row['content'].replace('\r\n', '\n').split('\n'))}):
            raise ValueError('Invalid candidate span or content')
        if row['path'] in versions and versions[row['path']] != row['content_hash']:
            raise ValueError('Inconsistent candidate source versions')
        versions[row['path']] = row['content_hash']
    selected, seen, decisions, used = [], set(), [], 0
    for index, row in enumerate(rows):
        key = (row['path'], row['start_line'], row['end_line'], row['content_hash'])
        container = next((number for number, parent in enumerate(selected)
                          if parent['path'] == row['path'] and parent['content_hash'] == row['content_hash']
                          and parent['start_line'] <= row['start_line'] <= row['end_line'] <= parent['end_line']
                          and row['content'] in parent['content']), None)
        decision = ('exact_duplicate' if key in seen else 'single_fragment_contained' if container is not None
                    else 'remaining_capacity' if used + len(row['content']) > max_chars else 'selected')
        if decision == 'selected':
            selected.append(dict(row))  # No provenance metadata added to the model request.
            seen.add(key)
            used += len(row['content'])
        decisions.append({'candidate': index, 'path': row['path'], 'start_line': row['start_line'],
                          'end_line': row['end_line'], 'decision': decision,
                          'container_selected_index': container, 'chars': len(row['content'])})
    return selected, {'policy': 'containment-read-first-v1', 'selected_chars': used,
                      'selected_fragments': len(selected), 'max_chars': max_chars, 'decisions': decisions}


def patch_messages(checkpoint, config, evidence):
    shared = checkpoint['metrics']['budget_accounted_tokens']
    limits = checkpoint['localization_result']['stage_limits']
    available = min(limits['patch'], max(0, config.token_budget - shared - limits['verification_reserve']))
    payload = {'description': checkpoint['description'], 'allowed_files': checkpoint['allowed_files'],
               'fragments': evidence, 'budget_state': {'patch_tokens': available, 'verification_reserve': limits['verification_reserve']},
               'instruction': 'Localization has ended. Return evidence-supported edits now, or an empty edits array. '
                              'Repair every behavior in the public description and preserve normal behavior.'}
    return [{'role': 'system', 'content': SYMBOL_SYSTEM}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]


def compare(checkpoint, config):
    pool = checkpoint['pool']
    baseline = select_evidence(pool['reads'], pool['seeds'], config.search_max_chars)
    variant, decisions = containment_evidence(pool['reads'], pool['seeds'], config.search_max_chars)
    a, b = patch_messages(checkpoint, config, baseline), patch_messages(checkpoint, config, variant)
    baseline_lines = {(row['path'], row['content_hash'], line) for row in baseline
                      for line in range(row['start_line'], row['end_line'] + 1)}
    variant_lines = {(row['path'], row['content_hash'], line) for row in variant
                     for line in range(row['start_line'], row['end_line'] + 1)}
    # This checks whole-fragment editability, stronger than union-of-lines coverage.
    preserved = [any(row['path'] == parent['path'] and row['content_hash'] == parent['content_hash']
                     and parent['start_line'] <= row['start_line'] <= row['end_line'] <= parent['end_line']
                     and row['content'] in parent['content'] for parent in variant) for row in baseline]
    return {'baseline_fragments': len(baseline), 'variant_fragments': len(variant),
            'baseline_chars': sum(len(row['content']) for row in baseline), 'variant_chars': decisions['selected_chars'],
            'baseline_message_json_chars': len(json.dumps(a, ensure_ascii=False)),
            'variant_message_json_chars': len(json.dumps(b, ensure_ascii=False)),
            'baseline_request_estimate': request_breakdown(a, [])['request_estimate'],
            'variant_request_estimate': request_breakdown(b, [])['request_estimate'],
            'baseline_prompt_hash': object_hash(a), 'variant_prompt_hash': object_hash(b),
            'same_complete_request': a == b, 'baseline_lines_lost': len(baseline_lines - variant_lines),
            'lines_gained': len(variant_lines - baseline_lines), 'baseline_whole_fragments_preserved': all(preserved),
            'baseline_fragment_preservation': preserved, 'selection': decisions, 'fragments': variant}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--experiment', type=Path, required=True, help='Completed compact experiment used to verify baseline requests')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for item in args.source:
        name, separator, path = item.partition('=')
        if not separator or not path or name in roots:
            parser.error('Supply unique SOURCE=PATH directories')
        roots[name] = Path(path).resolve()
    experiment = json.loads(args.experiment.read_text(encoding='utf-8'))
    analysis = json.loads((args.experiment.parent / 'analysis.json').read_text(encoding='utf-8'))
    if not experiment['complete'] or analysis['experiment_sha256'] != file_hash(args.experiment):
        raise ValueError('Expected the unchanged complete analyzed experiment')
    protocol = experiment['protocol']
    manifest = DATA / relative_path(protocol['manifest'])
    if file_hash(manifest) != protocol['manifest_sha256']:
        raise ValueError('Frozen manifest changed')
    data, entries = load_manifest(manifest)
    if set(roots) != {name for name, _, _ in entries}:
        raise ValueError('Supply all frozen source groups')
    output = args.output.resolve()
    checkpoints = [ROOT / relative_path(record['path']) for record in protocol['checkpoints'].values()]
    if output.exists() or any(output.is_relative_to(path) for path in
                              [*roots.values(), args.experiment.parent.resolve(), *(p.parent.resolve() for p in checkpoints)]):
        raise ValueError('Use a fresh output outside sources and old experiments')
    config = RunConfig(**data['config'])
    tasks = []
    for name, catalog, task in entries:
        record = protocol['checkpoints'][task]
        path = ROOT / relative_path(record['path'])
        if not path.resolve().is_relative_to(ROOT) or file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint changed')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        cases = json.loads(catalog.read_text(encoding='utf-8'))['cases']
        description = next(case['public_problem'] for case in cases if case['case_id'] == task)
        validate_localization(checkpoint, roots[name] / task / 'before', description, checkpoint['allowed_files'], config)
        result = compare(checkpoint, config)
        historical = next(row for row in experiment['patch_runs'] if row['task_id'] == task and row['policy'] == 'read-first')
        if result['baseline_prompt_hash'] != historical['worker']['patch_prompt_hash']:
            raise ValueError('Offline baseline differs from actual frozen request')
        tasks.append({'task_id': task, 'checkpoint_sha256': file_hash(path), **result})
    changed = [row['task_id'] for row in tasks if not row['same_complete_request']]
    report = {'purpose': 'offline-containment-packing-v1', 'model_calls': 0, 'new_localizations': 0,
              'algorithm_sha256': file_hash(Path(__file__)), 'experiment_sha256': file_hash(args.experiment),
              'tasks': tasks, 'changed_request_tasks': changed,
              'decision': 'no_live_run_identical_inputs' if not changed else 'review_changed_requests_before_live_run',
              'limitations': 'No token or repair-success improvement claim. Full-fragment containment is stricter '
                             'than union-of-lines coverage. Metadata stays outside model evidence.'}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'packing.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in tasks:
        print(row['task_id'], row['baseline_message_json_chars'], '->', row['variant_message_json_chars'],
              'same_request', row['same_complete_request'], 'anchors_preserved', row['baseline_whole_fragments_preserved'])
    print('Decision:', report['decision'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
