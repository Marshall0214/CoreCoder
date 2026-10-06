"""Offline analysis with deduplicated shared-localization cost for packing comparison."""
import argparse
import json
from pathlib import Path

from docs.experiments.definition_patch_analysis_v1 import analyze as patch_analysis
from evals.real_suite import file_hash


def analyze(root):
    result = patch_analysis(root)
    report = json.loads((root / 'experiment.json').read_text(encoding='utf-8'))
    checkpoints = report['protocol']['checkpoints']
    unique = {}
    for record in checkpoints.values():
        key = record['checkpoint_hash']
        if key in unique and unique[key] != record['localization_tokens']:
            raise ValueError('Conflicting cost for shared checkpoint')
        unique[key] = record['localization_tokens']
    pools = [run['worker']['candidate_pool_hash'] for run in report['patch_runs']]
    if len(set(pools)) != 1:
        raise ValueError('Packing experiment must use identical candidate pools')
    result.update(shared_actual_localization_tokens=sum(unique.values()),
                  unique_shared_localization_count=len(unique), same_candidate_pool=True,
                  historical_plus_new_actual_tokens=sum(unique.values()) + result['new_patch_tokens'],
                  raw_report_branch_pipeline_sum=report['pipeline_tokens'],
                  cost_note='Raw runner pipeline_tokens sums standalone branch equivalents and duplicates shared localization. '
                            'New billed/runtime usage is new_patch_tokens only; historical_plus_new counts shared localization once.')
    for output, run in zip(result['runs'], report['patch_runs'], strict=True):
        packing = run['worker']['packing']
        output['packing'] = packing
        output['evidence_chars'] = run['worker']['evidence_chars']
        output['candidate_pool_hash'] = run['worker']['candidate_pool_hash']
        output['patch_prompt_hash'] = run['worker']['patch_prompt_hash']
    result['diagnostic_sha256'] = file_hash(Path(__file__))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    output = args.run / 'analysis.json'
    if output.exists():
        raise ValueError('Analysis already exists')
    output.write_text(json.dumps(analyze(args.run), ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
