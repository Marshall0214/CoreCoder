"""Audit a frozen candidate against separate post-hoc preservation probes; no LLM."""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.runner import changes, snapshot
from repairflow import checks
from repairflow.bundles import read, tree_hash, write
from repairflow.issue_repair import trusted_task
from sandbox import runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Require a fresh output under project .tmp')
    packet = ROOT / 'docs/compact_observations_20261029'
    frozen = read(ROOT / 'docs/compact-observations-20261029.json')
    for name, digest in frozen['files'].items():
        if hashlib.sha256((packet / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen evidence changed: ' + name)
    plan = read(packet / 'run-plan.json')
    prepared = ROOT / '.tmp/github-issue-acceptance-20261019/click-3887-v2'
    configuration = ROOT / 'configs/issue-tasks/click-3887.json'
    candidate = ROOT / '.tmp/issue-compact-live-20261029/click-3887-qwen35-compact-001/workspace'
    task, settings = trusted_task(prepared, configuration)
    if task['source_sha256'] != plan['source_sha256'] or task['harness_sha256'] != plan['harness_sha256']:
        raise ValueError('Prepared task differs from the frozen run')
    changed, patch = changes(snapshot(prepared / 'source'), snapshot(candidate))
    if changed != ['src/click/termui.py'] or patch != (packet / 'live/patch.diff').read_text(encoding='utf-8'):
        raise ValueError('Candidate differs from the frozen final patch')
    policy = runner.preflight(settings['image'])
    if policy['image_id'] != plan['sandbox']['image_id']:
        raise ValueError('Sandbox image differs from the frozen run')
    inputs = {'prepared': prepared, 'candidate': candidate, 'configuration': configuration,
              'diagnostic_source': ROOT / 'evals/diagnostics/click_style_preservation.py',
              'frozen_summary': ROOT / 'docs/compact-observations-20261029.json'}

    def fingerprints():
        return {name: tree_hash(path) if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in inputs.items()}

    before = fingerprints()
    output.mkdir(parents=True)
    diagnostic = output / 'diagnostic-harness'
    diagnostic.mkdir()
    shutil.copyfile(inputs['diagnostic_source'], diagnostic / 'test_admission.py')
    write(output / 'run-plan.json', {'scope': 'Post-hoc compatibility review, not new frozen scoring or model inference',
          'fresh_model_calls': 0, 'learning_task_runs_used': 1, 'method_rounds_used': 1,
          'input_hashes': before, 'sandbox': policy, 'probe_count': 6,
          'original_groups': ['Reproduce', 'Preserve'], 'diagnostic_group': 'StylePreservation'})
    results = {}
    try:
        for label, source in (('base', prepared / 'source'), ('candidate', candidate)):
            results[label] = {}
            for group in ('Reproduce', 'Preserve', 'StylePreservation'):
                logs = output / label / group
                logs.mkdir(parents=True)
                harness = diagnostic if group == 'StylePreservation' else prepared / 'public'
                result = runner.run(source, harness, task['package'], task['source_root'], logs, group,
                                    checks.historical.admission.previous.BOOT, policy, runner.owner(output))
                result['cases'] = dict(re.findall(r'^(test_\w+) \([^\n]*\) \.\.\. (ok|FAIL|ERROR)',
                    (logs / (group + '.stderr.txt')).read_text(encoding='utf-8'), flags=re.MULTILINE))
                if len(result['cases']) != result['tests_run']:
                    raise ValueError('Per-case log count differs from runner result')
                results[label][group] = result
            write(output / 'progress.json', results)
        base = results['base']['StylePreservation']
        candidate_result = results['candidate']['StylePreservation']
        eligible = (base['successful'] and base['tests_run'] == 6 and not base['errors'] and not base['skipped'])
        regressions = [name for name, status in candidate_result['cases'].items()
                       if base['cases'].get(name) == 'ok' and status != 'ok'] if eligible else []
        report = {'status': 'completed', 'scope': 'Post-hoc development diagnosis; original reports and scoring unchanged',
                  'fresh_model_calls': 0, 'cloud_calls': 0, 'sandbox': policy, 'results': results,
                  'diagnostic_base_eligible': eligible, 'new_regressions': regressions,
                  'review_decision': 'needs_revision' if eligible and regressions else
                                     'no_regression_in_probes' if eligible else 'diagnosis_ineligible',
                  'limits': 'Locally authored probes after seeing the patch; not upstream full suite or independent grading.'}
        write(output / 'report.json', report)
        print(json.dumps({key: report[key] for key in ('status', 'fresh_model_calls', 'diagnostic_base_eligible',
                                                      'new_regressions', 'review_decision')}, ensure_ascii=False))
    finally:
        remaining = runner.control(['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + runner.owner(output)])
        write(output / 'postflight.json', {'inputs_unchanged': before == fingerprints(),
              'diagnostic_harness_unchanged': (diagnostic / 'test_admission.py').read_bytes() == inputs['diagnostic_source'].read_bytes(),
              'remaining_owned_containers': remaining.decode().split()})


if __name__ == '__main__':
    main()
