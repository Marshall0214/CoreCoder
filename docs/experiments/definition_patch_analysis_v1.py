"""Offline cost, prompt parity and patch diagnostics for the definition patch pilot."""
import argparse
import json
from pathlib import Path

from evals.real_suite import file_hash
from evals.staged_repair import object_hash


def analyze(root):
    path = root / 'experiment.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    if not report['complete'] or len(report['patch_runs']) != 2:
        raise ValueError('Expected completed two-branch pilot')
    rows, non_evidence, diff_hashes = [], [], []
    for run in report['patch_runs']:
        folder = Path(run['artifacts'])
        messages = json.loads((folder / 'patch-request.json').read_text(encoding='utf-8'))
        payload = json.loads(messages[1]['content'])
        non_evidence.append(object_hash({'system': messages[0]['content'],
                                       'payload': {k: v for k, v in payload.items() if k != 'fragments'}}))
        diff_hashes.append(file_hash(folder / 'patch.diff'))
        verification = run['verification']
        worker = run['worker']
        cost = worker['budget_accounting']
        if cost['pipeline_equivalent_tokens'] != cost['shared_localization_tokens'] + cost['patch_tokens']:
            raise ValueError('Pipeline cost does not add up')
        rows.append({'localization_policy': run['policy'], 'status': run['status'], 'accepted': run['accepted'],
                     'localization_tokens_previously_spent': cost['shared_localization_tokens'],
                     'new_patch_tokens': cost['patch_tokens'], 'pipeline_tokens': cost['pipeline_equivalent_tokens'],
                     'new_model_calls': run['metrics']['llm_calls'], 'target_passed': verification['target']['passed'],
                     'controls_passed': verification['regression']['passed'],
                     'scope_violations': verification['scope_violations'],
                     'selected_ranges': [{k: f[k] for k in ('path', 'start_line', 'end_line')} for f in payload['fragments']],
                     'patch_request_sha256': file_hash(folder / 'patch-request.json'), 'patch_diff_sha256': diff_hashes[-1]})
    if non_evidence[0] != non_evidence[1]:
        raise ValueError('Paired patch prompts differ outside evidence')
    return {'experiment_sha256': file_hash(path), 'benchmark_eligible': False, 'same_non_evidence_prompt': True,
            'same_applied_diff': diff_hashes[0] == diff_hashes[1], 'runs': rows,
            'new_patch_tokens': sum(r['new_patch_tokens'] for r in rows),
            'pipeline_tokens': sum(r['pipeline_tokens'] for r in rows),
            'interpretation': 'Post-hoc single development task; failed runs remain visible; Controls are not the upstream suite.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    output = args.run / 'analysis.json'
    if output.exists():
        raise ValueError('Analysis already exists')
    output.write_text(json.dumps(analyze(args.run), ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
