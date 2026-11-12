"""Cross-check mechanical audits and archive a bounded evidence packet on D:."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BATCH = ROOT / '.tmp/harness2-v2-50-20261106'
PACKET = ROOT / 'docs/harness2_analysis_20261107'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    main_audit = read(OUT / 'main-analysis.json')
    cost = read(OUT / 'cost-analysis.json')
    selection = read(OUT / 'selection-analysis.json')
    failures = read(OUT / 'failure-analysis.json')
    historical = read(OUT / 'historical-feedback-audit.json')
    report = read(BATCH / 'report.json')
    comparison = read(BATCH / 'comparison.json')
    rows = report['tasks']['harness2']
    checks = {}
    checks['fifty_graded_rows'] = len(rows) == 50 and all(r['status']=='graded' for r in rows.values())
    checks['independent_results_reconcile'] = sum(r['resolved'] is True for r in rows.values()) == comparison['resolved'] == 25
    checks['all_ppc_complete'] = sum(r['result']['optimization_complete'] is True for r in rows.values()) == 50
    checks['calls_reconcile'] = sum(r['usage']['fresh_model_calls'] for r in rows.values()) == cost['summary']['model_calls'] == 3417
    checks['phase_calls_reconcile'] = sum(p['calls'] for p in cost['by_phase'].values()) == 3417
    checks['known_native_tokens_reconcile'] = sum(p['native_known_total_tokens_minimum'] for p in cost['by_phase'].values()) == 59796366
    checks['known_unknown_calls_reconcile'] = sum(t.get('known_call_events',0) for t in cost['traces']) + cost['summary']['missing_native_usage_event_count'] == 3417
    checks['feedback_requests_reconcile'] = sum(cost['feedback_patch_statuses'].values()) == 1181
    checks['feedback_rejections_reconcile'] = sum(cost['feedback_patch_error_codes'].values()) == 1115
    checks['feedback_terminals_reconcile'] = sum(cost['feedback_statuses'].values()) == 200
    checks['failures_reconcile'] = sum(failures['summary']['categories'].values()) == 25
    checks['selection_outcomes_reconcile'] = sum(selection['counts'][k] for k in (
        'public_true_independent_true', 'public_true_independent_false',
        'public_false_independent_true', 'public_false_independent_false')) == 50
    checks['all_post_apply_checks_unreadable_runner'] = len(main_audit['post_feedback_sandbox_records']) == 35 and all(
        r['returncode']==2 and "can't open file '/runner.py'" in r['stderr']
        and 'Input/output error' in r['stderr'] for r in main_audit['post_feedback_sandbox_records'])
    checks['shared_historical_runner_problem'] = all(
        historical['arms'][arm]['applied_patches'] == historical['arms'][arm]['blocked_with_runner_py_io_stderr'] == count
        for arm,count in [('historical_control',11),('historical_harness',24),('current_harness',35)])
    checks['frozen_execution_code_unchanged'] = all(main_audit['source_files_verified'].values())
    checks['original_inputs_unchanged'] = all(sha(BATCH/name)==expected
        for name,expected in main_audit['input_hashes'].items())
    checks['native_trace_hashes_match'] = all(sha(ROOT/t['path'])==t['sha256'] for t in cost['traces'])
    launch = ROOT / 'docs/harness2_rerun50_20261106'
    launch_manifest = read(launch / 'manifest.json')
    checks['launch_packet_unchanged'] = all(sha(launch/r['path'])==r['sha256'] for r in launch_manifest['files'])
    assert all(checks.values()), checks
    save(OUT / 'verification.json', {'passed': True, 'checks': checks,
        'fresh_model_calls': 0, 'test_executions': 0,
        'original_source_hashes': main_audit['input_hashes'],
        'native_trace_files_verified': len(cost['traces']),
        'launch_packet_files_verified': len(launch_manifest['files'])})
    summary = {'schema': 'harness2-fifty-analysis-summary-v1', 'date': '2026-11-07',
        'stage': 'completed; read-only post-hoc analysis', 'output_directory': str(BATCH),
        'resolved': 25, 'tasks': 50, 'historical_control_resolved': 24, 'historical_harness_resolved': 27,
        'fresh_evaluation_model_calls': 3417, 'fresh_analysis_model_calls': 0,
        'analysis_test_executions': 0, 'wall_seconds': main_audit['wall_seconds'],
        'original_task_complete_token_lower_bound': 30859536,
        'native_known_token_lower_bound': 59796366, 'actual_total_tokens': None,
        'missing_usage_calls': 30, 'feedback_requests': 1181, 'rejected_nochange_requests': 1115,
        'feedback_applied_patches': 35, 'post_apply_runner_io_errors': 35,
        'old_control_post_apply_io_errors': 11, 'old_harness_post_apply_io_errors': 24,
        'feedback_final_states': cost['feedback_statuses'],
        'failure_categories': failures['summary']['categories'],
        'repository_counts': main_audit['repository_counts'],
        'limitations': main_audit['interpretation_limits'],
        'remote_langfuse_all_generation_receipts_verified': False,
        'verification': checks,
        'next_priority': ['sandbox runner transport and error classification',
                          'feedback context and patch schema', 'small mechanism acceptance before full rerun']}
    save(ROOT / 'docs/harness2-analysis-20261107.json', summary)
    PACKET.mkdir(exist_ok=True)
    names = ('analyze_main.py', 'cost_analysis.py', 'selection_analysis.py', 'analyze_failures.py',
        'historical_feedback_audit.py', 'finalize_analysis.py', 'main-analysis.json', 'cost-analysis.json',
        'selection-analysis.json', 'failure-analysis.json', 'historical-feedback-audit.json',
        'provider-truncation-excerpt.json', 'verification.json', 'cost-notes.md', 'selection-notes.md',
        'failure-notes.md', 'historical-feedback-notes.md')
    for name in names:
        shutil.copyfile(OUT/name, PACKET/name)
    shutil.copyfile(ROOT/'docs/harness2-analysis-20261107.json', PACKET/'summary.json')
    for name in ('comparison.json','controller.json','report.json'):
        shutil.copyfile(BATCH/name, PACKET/('original-'+name))
    files = [{'path': f.relative_to(PACKET).as_posix(), 'sha256': sha(f), 'bytes': f.stat().st_size}
             for f in sorted(PACKET.rglob('*')) if f.is_file() and f.name!='manifest.json']
    manifest = {'schema': 'harness2-analysis-evidence-v1', 'stage': 'completed post-hoc audit',
        'source': str(BATCH), 'scope': 'Audits and selected original summaries; raw traces remain in original batch.',
        'files': files, 'file_count': len(files), 'bytes': sum(f['bytes'] for f in files)}
    save(PACKET/'manifest.json', manifest)
    assert all(sha(PACKET/f['path'])==f['sha256'] for f in files)
    print(json.dumps({'passed': True, 'cross_checks': len(checks),
        'native_traces_verified': len(cost['traces']), 'launch_files_verified': len(launch_manifest['files']),
        'archive_files': len(files), 'archive_bytes': manifest['bytes'], 'analysis_model_calls': 0,
        'test_executions': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
