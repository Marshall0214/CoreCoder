"""Post-hoc replay of frozen event checks; never calls or feeds back to a model."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from evals.contract_feedback import check_candidate
from evals.runner import DEFAULT_SUITE, digest, snapshot
from evals.runtime import Events
from evals.schema import RunConfig, relative_path
from tests.test_check_scenarios import CORRECT


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def frozen_runs(root):
    root = root.resolve()
    state, freeze = load(root / 'comparison.json'), load(root / 'freeze.json')
    if state.get('completed') is not True or state.get('stop_reason') is not None:
        raise ValueError('Audit requires a completed frozen comparison')
    rows = []
    seen = set()
    for arm, ids in state['run_ids'].items():
        if '/' in relative_path(arm):
            raise ValueError('Arm must be a single directory name')
        for run_id in ids:
            if '/' in relative_path(run_id):
                raise ValueError('Run ID must be a single directory name')
            path = (root / arm / run_id / 'report.json').resolve()
            if not path.is_relative_to(root) or run_id in seen:
                raise ValueError('Invalid or duplicate run location')
            seen.add(run_id)
            report = load(path)
            if report['task_id'] != 'event-replay' or report['run_id'] != run_id:
                raise ValueError('This public-contract fault audit supports event-replay only')
            if report['implementation']['source_hash'] != freeze['implementation']['source_hash']:
                raise ValueError('Report source differs from frozen version')
            code_path = path.parent / 'public-contract-checks.py'
            if code_path.is_symlink():
                raise ValueError('Frozen checks cannot be a linked file')
            code = code_path.read_bytes() if code_path.exists() else None
            if code is not None and hashlib.sha256(code).hexdigest() != report['worker']['public_checks']['code_hash']:
                raise ValueError('Frozen public checks changed')
            rows.append((arm, report, code))
    if len(rows) != state['planned_runs']:
        raise ValueError('Missing scheduled reports')
    return rows, freeze


def audit(root, output):
    rows, freeze = frozen_runs(root)
    fixture = DEFAULT_SUITE / 'localization-v1/event-replay'
    if digest(snapshot(fixture)) != freeze['fixtures']['event-replay']:
        raise ValueError('Original task fixture changed')
    output.mkdir(parents=True, exist_ok=False)
    result = {'scope': 'post-hoc public-contract fault replay; no model feedback or check selection',
              'correct_behavior_hash': hashlib.sha256(CORRECT.encode()).hexdigest(),
              'auditor_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'frozen_source_hash': freeze['implementation']['source_hash'], 'runs': [], 'pairs': []}
    paired = {}
    for arm, report, code in rows:
        row = {'arm': arm, 'run_id': report['run_id'], 'repetition': report['repetition'], 'outcomes': {}}
        checks = report.get('worker', {}).get('public_checks', {})
        row['retained_scenarios'] = checks.get('retained_scenario_diagnostics', [])
        row['check_hash'] = checks.get('code_hash')
        paired.setdefault(report['repetition'], []).append(report)
        if code is None:
            row['unavailable_reason'] = 'No frozen retained checks'
        else:
            for variant in ('original', 'correct', 'global-id', 'early-stop'):
                run_root = output / arm / report['run_id'] / variant
                run_root.mkdir(parents=True)
                workspace = run_root / 'workspace'
                shutil.copytree(fixture / 'workspace', workspace, ignore=shutil.ignore_patterns('__pycache__'))
                if variant != 'original':
                    source = CORRECT
                    if variant == 'global-id':
                        source = source.replace("(event['tenant'], event['event_id'])", "event['event_id']")
                    if variant == 'early-stop':
                        source = source.replace('            continue', '            return state')
                    (workspace / 'projector.py').write_text(source, encoding='utf-8')
                outcome, _ = check_candidate(workspace, code.decode('utf-8'), RunConfig(**report['config']),
                                             Events(run_root / 'trace.jsonl', 'posthoc'), variant)
                row['outcomes'][variant] = outcome
        result['runs'].append(row)
    for rep, reports in paired.items():
        if len(reports) != 2:
            raise ValueError('Missing paired run')
        stages = [r['worker']['patch_stages'][0] for r in reports]
        result['pairs'].append({'repetition': rep,
                                'prompt_equal': stages[0]['prompt_hash'] == stages[1]['prompt_hash'],
                                'evidence_equal': stages[0]['evidence_manifest'] == stages[1]['evidence_manifest'],
                                'initial_output_equal': stages[0]['final_message'] == stages[1]['final_message']})
    (output / 'fault-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New audit directory')
    args = parser.parse_args()
    audit(args.input, args.output)
    print(args.output.resolve() / 'fault-audit.json')


if __name__ == '__main__':
    main()
