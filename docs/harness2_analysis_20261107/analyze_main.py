"""Read-only provenance and provider-log audit; never imports or runs the agent."""
import collections
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BATCH = ROOT / '.tmp/harness2-v2-50-20261106'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = read(BATCH / 'report.json')
    protocol = read(BATCH / 'protocol.json')
    controller = read(BATCH / 'controller.json')
    historical = read(BATCH / 'historical/report.json')
    start = datetime.fromisoformat(read(BATCH / 'launcher.json')['started_at'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(controller['ended_at'])
    rows = report['tasks']['harness2']
    sandbox_records = []
    sandbox_counts = collections.Counter()
    for task, row in rows.items():
        for rollout in row['result']['rollouts']:
            feedback = Path(rollout['folder']) / 'feedback'
            files = [feedback / 'validation-000/public-logs/Reproduce-sandbox.json',
                     *sorted(feedback.glob('rounds/*/validation/public-logs/Reproduce-sandbox.json'))]
            for path in files:
                if not path.exists():
                    continue
                receipt = read(path)
                phase = 'after_feedback_patch' if 'rounds' in path.parts else 'initial_validation'
                stderr = path.with_name('Reproduce.stderr.txt')
                error = stderr.read_text(encoding='utf-8', errors='replace') if stderr.exists() else ''
                sandbox_counts[(phase, receipt['sandbox_status'])] += 1
                if phase == 'after_feedback_patch':
                    sandbox_records.append({'task_id': task, 'label': rollout['label'],
                        'path': str(path.relative_to(ROOT)), 'sha256': sha(path),
                        'status': receipt['sandbox_status'], 'returncode': receipt['returncode'],
                        'runner_host_path_characters': len(str(path.with_name('Reproduce-runner.py'))),
                        'stderr': error, 'stderr_sha256': sha(stderr) if stderr.exists() else None})
    repositories = collections.defaultdict(collections.Counter)
    for case in protocol['cases']:
        task = case['task_id']
        repo = repositories[case['repo']]
        repo['tasks'] += 1
        for name, group in [('control', report['tasks']['no_harness']),
                            ('old_harness2', historical['tasks']['harness2']),
                            ('new_harness2', rows)]:
            repo[name] += group[task].get('resolved') is True

    samples = []
    for task in ('click-style-color-validation', 'click-flag-envvar', 'boltons-split-zero',
                 'more-negative-range-slice'):
        # Inspect agg1 consistently, even when delivery selected an earlier probe.
        folder = next(Path(r['folder']) for r in rows[task]['result']['rollouts']
                      if r['label'] == 'agg1') / 'feedback'
        trace = folder / 'trace.jsonl'
        events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        begun = next(e for e in events if e['event'] == 'llm_started')
        finished = next(e for e in events if e['event'] in ('llm_finished', 'llm_failed'))
        messages_file = folder / 'rounds/001/messages.json'
        messages = read(messages_file)
        payload = json.loads(messages[-1]['content'])
        round_report = read(folder / 'rounds/001/report.json')
        samples.append({'task_id': task, 'rollout': 'agg1', 'folder': str(folder.relative_to(ROOT)),
            'call_interval_utc': [begun['time'], finished['time']],
            'system_characters': len(messages[0]['content']),
            'payload_characters': len(messages[-1]['content']),
            'source_characters': sum(len(f['content']) for f in payload['current_fragments']),
            'source_files': len(payload['current_fragments']),
            'public_feedback_character_offset': messages[-1]['content'].find('"public_feedback"'),
            'patch_status': round_report.get('patch_status'),
            'patch_error': round_report.get('patch_error'),
            'usage': round_report.get('usage'), 'call_event': finished,
            'overlapping_provider_warnings': []})

    log = Path('C:/Users/admin/AppData/Local/Ollama/server.log')
    warnings = []
    if log.exists():
        with log.open(encoding='utf-8', errors='replace') as stream:
            for number, line in enumerate(stream, 1):
                if 'truncating input prompt' not in line:
                    continue
                match = re.search(r'time=(\S+)', line)
                if not match:
                    continue
                date = datetime.fromisoformat(match[1])
                if not start <= date <= end:
                    continue
                entry = {'source_line': number, 'text': line.strip(), 'time_unix': date.timestamp()}
                warnings.append(entry)
                for sample in samples:
                    first, last = sample['call_interval_utc']
                    if first <= date.timestamp() <= last:
                        sample['overlapping_provider_warnings'].append(entry)

    evidence = {
        'schema': 'harness2-fifty-readonly-analysis-v1',
        'fresh_model_calls': 0, 'test_executions': 0,
        'started_at_beijing': start.astimezone(timezone(timedelta(hours=8))).isoformat(),
        'ended_at_beijing': end.astimezone(timezone(timedelta(hours=8))).isoformat(),
        'wall_seconds': (end-start).total_seconds(),
        'results': read(BATCH / 'comparison.json'),
        'repository_counts': dict(repositories),
        'sandbox_counts': [{'phase': k[0], 'status': k[1], 'count': v}
                           for k, v in sandbox_counts.items()],
        'post_feedback_sandbox_records': sandbox_records,
        'source_files_verified': {name: sha(ROOT / name) == expected
                                  for name, expected in protocol['source_files'].items()},
        'input_hashes': {name: sha(BATCH / name) for name in
                         ('report.json', 'protocol.json', 'controller.json', 'comparison.json',
                          'reuse-verification.json', 'historical/report.json')},
        'provider_log': {'path': str(log), 'sha256_at_analysis': sha(log) if log.exists() else None,
            'batch_time_window_truncation_warnings': len(warnings),
            'attribution': 'Server-wide time-window count; not all warnings assigned to unique requests.',
            'excerpt': 'provider-truncation-excerpt.json'},
        'feedback_input_examples': samples,
        'interpretation_limits': [
            'Provider warnings confirm truncation, not which exact portions were retained.',
            'Overlapping timestamps are corroborating evidence, not unique request identifiers.',
            'No causal estimate separates prompt changes, repeated sampling and public selection.',
            'Independent results cover hand-authored Target/Controls, not entire upstream suites.',
            'Historical controls reused; no equal-compute or held-out generalization claim.'],
    }
    OUT.mkdir(exist_ok=True)
    (OUT / 'main-analysis.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    excerpt = {'source': str(log), 'source_sha256': evidence['provider_log']['sha256_at_analysis'],
               'batch_window': [start.isoformat(), end.isoformat()],
               'warning_count': len(warnings), 'samples': warnings[:8],
               'per_call_samples': {s['task_id']: s['overlapping_provider_warnings'] for s in samples}}
    (OUT / 'provider-truncation-excerpt.json').write_text(json.dumps(excerpt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'repositories': dict(repositories), 'wall_seconds': evidence['wall_seconds'],
                     'all_source_hashes_match': all(evidence['source_files_verified'].values()),
                     'warning_count_in_window': len(warnings),
                     'overlapping_examples': {s['task_id']: len(s['overlapping_provider_warnings']) for s in samples}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
