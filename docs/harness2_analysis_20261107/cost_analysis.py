"""Read-only post-hoc cost/behavior accounting. No model, network, or evaluation."""
import collections
import datetime as dt
import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '.tmp/harness2-v2-50-20261106'
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def relative(path):
    return Path(path).relative_to(ROOT).as_posix()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric(value):
    return type(value) in (int, float)


def describe(values):
    return {'count': len(values), 'sum': sum(values),
            'min': min(values) if values else None,
            'median': statistics.median(values) if values else None,
            'max': max(values) if values else None}


report = read(SOURCE / 'report.json')
comparison = read(SOURCE / 'comparison.json')
controller = read(SOURCE / 'controller.json')
launcher = read(SOURCE / 'launcher.json')
rows = report['tasks']['harness2']
assert len(rows) == 50 and all(r['status'] == 'graded' for r in rows.values())
assert sum(r['resolved'] for r in rows.values()) == 25
by_phase = collections.defaultdict(lambda: collections.Counter())
feedback_status = collections.Counter()
patch_status = collections.Counter()
patch_codes = collections.Counter()
candidate_status = collections.Counter()
candidate_action_status = collections.Counter()
candidate_action_names = collections.Counter()
candidate_duplicate_names = collections.Counter()
reader_format_errors = collections.Counter()
reader_exact_duplicate_reads = 0
reader_overlap_characters = 0
reader_read_characters = 0
reader_unique_characters = 0
feedback_rounds = []
feedback_details = []
reader_details = []
candidate_details = []
trace_facts = []
task_details = []
unknown_phases = []
metrics_missing_calls = []
input_frequency = collections.defaultdict(collections.Counter)
missing_native_calls = []
request_estimates_by_phase = collections.defaultdict(list)
call_seconds_by_phase = collections.defaultdict(list)
native_tokens_by_phase = collections.defaultdict(collections.Counter)
feedback_nochange_known_tokens = 0
feedback_rejected_known_tokens = 0
feedback_attempts_by_limit = 0
feedback_nochange_count = 0
feedback_rejected_count = 0
feedback_round_time = []
feedback_applied_no_change = 0
feedback_repeated_state_count = 0
native_usage_events = []
blocked_validation_records = []


def trace(path, phase, task, label):
    if not path.exists():
        raise FileNotFoundError(path)
    events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    known = collections.Counter()
    for event in events:
        if event['event'] == 'request_preflight':
            estimate = event.get('request_estimate')
            if numeric(estimate):
                request_estimates_by_phase[phase].append(estimate)
                known['preflight_events'] += 1
                if estimate > event.get('provider_context_tokens', float('inf')):
                    known['estimated_over_declared_context'] += 1
        if event['event'] in ('llm_finished', 'llm_failed'):
            known['terminal_call_events'] += 1
            if numeric(event.get('seconds')):
                call_seconds_by_phase[phase].append(event['seconds'])
            if event['event'] == 'llm_failed':
                known['failed_call_events'] += 1
            inp, out = event.get('prompt_tokens'), event.get('completion_tokens')
            if type(inp) is int and type(out) is int and event.get('usage_known') is not False:
                known['known_call_events'] += 1
                known['input'] += inp
                known['output'] += out
                input_frequency[phase][inp] += 1
                native_usage_events.append({'phase': phase, 'task': task, 'label': label,
                                            'input': inp, 'output': out,
                                            'path': relative(path), 'sequence': event.get('sequence')})
            else:
                known['missing_usage_events'] += 1
                missing_native_calls.append({'phase': phase, 'task': task, 'label': label,
                                             'path': relative(path), 'event': event})
    for key, value in known.items():
        native_tokens_by_phase[phase][key] += value
    trace_facts.append({'path': relative(path), 'phase': phase, 'task': task, 'label': label,
                        'sha256': sha(path), **known})


for task, row in rows.items():
    usage = row['usage']
    details = {'task': task, 'resolved': row['resolved'], 'seconds': row['result']['seconds'],
               'fresh_calls': usage['fresh_model_calls'], 'tokens_complete': usage['tokens'],
               'phase_complete_token_sum_minimum': usage['known_tokens_minimum'],
               'feedback_rounds': 0, 'feedback_nochange': 0, 'feedback_rejected': 0,
               'feedback_round_limit_rollouts': 0}
    for phase_row in usage['phases']:
        phase = phase_row['phase']
        by_phase[phase]['records'] += 1
        by_phase[phase]['calls'] += phase_row['fresh_model_calls']
        if phase_row['tokens'] is None:
            by_phase[phase]['unknown_usage_records'] += 1
            unknown_phases.append({'task': task, **phase_row})
        else:
            by_phase[phase]['complete_phase_tokens_minimum'] += phase_row['tokens']
        folder = Path(phase_row['folder'])
        label = folder.name
        if phase == 'candidate':
            r = read(folder / 'agent/report.json')
            candidate_status[r['status']] += 1
            actions = read(folder / 'agent/actions.json')
            action_counts = collections.Counter()
            dupes = collections.Counter()
            seen = set()
            for action in actions:
                name = action.get('action', '<missing>')
                candidate_action_names[name] += 1
                candidate_action_status[action.get('status', '<missing>')] += 1
                action_counts[name] += 1
                marker = json.dumps([name, action.get('arguments')], sort_keys=True)
                if marker in seen:
                    candidate_duplicate_names[name] += 1
                    dupes[name] += 1
                seen.add(marker)
            candidate_details.append({'task': task, 'label': label, 'status': r['status'],
                                      'seconds': r['seconds'], 'calls': r['fresh_model_calls'],
                                      'changed_files': r.get('changed_files'), 'action_counts': dict(action_counts),
                                      'exact_duplicate_actions_after_first': dict(dupes),
                                      'metrics': r['metrics'], 'path': relative(folder / 'agent/report.json')})
            trace(folder / 'agent/trace.jsonl', phase, task, label)
            metrics = r['metrics']
        elif phase == 'feedback':
            p = folder / 'feedback/report.json'
            if not p.exists():
                assert phase_row['fresh_model_calls'] == 0
                continue
            r = read(p)
            metrics = r.get('metrics', {})
            feedback_status[r['status']] += 1
            feedback_rounds.append(r['feedback_rounds_attempted'])
            details['feedback_rounds'] += r['feedback_rounds_attempted']
            at_limit = r['status'] == 'feedback_round_limit'
            feedback_attempts_by_limit += at_limit
            details['feedback_round_limit_rollouts'] += at_limit
            previous_hashes = set()
            nochange = 0
            rejected = 0
            for rd in r.get('rounds', []):
                patch_status[rd.get('patch_status', '<missing>')] += 1
                if rd.get('patch_status') == 'rejected':
                    patch_codes[rd.get('patch_error', {}).get('code', '<missing>')] += 1
                    feedback_rejected_count += 1
                    rejected += 1
                before, after = rd.get('candidate_hash_before'), rd.get('candidate_hash')
                same = bool(before and after == before)
                nochange += same
                feedback_nochange_count += same
                if same and rd.get('patch_status') == 'applied':
                    feedback_applied_no_change += 1
                if after and after in previous_hashes:
                    feedback_repeated_state_count += 1
                if after:
                    previous_hashes.add(after)
                nums = list(rd.get('usage', {}).values())
                known = sum(n for n in nums if type(n) is int)
                if same:
                    feedback_nochange_known_tokens += known
                if rd.get('patch_status') == 'rejected':
                    feedback_rejected_known_tokens += known
                if numeric(rd.get('seconds')):
                    feedback_round_time.append(rd['seconds'])
            details['feedback_nochange'] += nochange
            details['feedback_rejected'] += rejected
            for validation in [folder / 'feedback/validation-000/report.json', *sorted((folder / 'feedback/rounds').glob('*/validation/report.json'))]:
                if not validation.exists():
                    continue
                validation_row = read(validation)
                if validation_row.get('status') == 'blocked':
                    blocked_validation_records.append({'task': task, 'label': label,
                        'path': relative(validation), 'infrastructure_error': validation_row.get('infrastructure_error'),
                        'has_public_check_result': validation_row.get('public_checks') is not None,
                        'initial_validation': 'validation-000' in validation.parts,
                        'candidate_hash': validation_row.get('candidate_hash')})
            feedback_details.append({'task': task, 'label': label, 'status': r['status'],
                                     'rounds': r['feedback_rounds_attempted'],
                                     'applied_patches': r.get('applied_patches'), 'accepted': r.get('accepted'),
                                     'no_change_rounds': nochange, 'rejected_rounds': rejected,
                                     'seconds': r.get('seconds'), 'metrics': metrics,
                                     'path': relative(p)})
            if (folder / 'feedback/trace.jsonl').exists():
                trace(folder / 'feedback/trace.jsonl', phase, task, label)
            else:
                assert phase_row['fresh_model_calls'] == 0
        else:
            r = read(folder / 'report.json')
            metrics = r['metrics']
            rr = read(folder / 'reader-report.json')
            spans = collections.defaultdict(list)
            prior = set()
            duplicate_reads = 0
            read_characters = 0
            for record in rr['reads']:
                if not record.get('ok'):
                    continue
                key = (record['path'], record['sha256'])
                start = record['offset']
                end = record['next_offset'] or record['total_characters']
                marker = (*key, start, end)
                duplicate_reads += marker in prior
                prior.add(marker)
                spans[key].append((start, end))
                read_characters += end - start
            unique_characters = 0
            for file_spans in spans.values():
                end = -1
                for start, stop in sorted(file_spans):
                    unique_characters += max(0, stop - max(start, end))
                    end = max(stop, end)
            for error in rr['format_errors']:
                reader_format_errors[error.get('format_error', '<missing>')] += 1
            reader_exact_duplicate_reads += duplicate_reads
            reader_read_characters += read_characters
            reader_unique_characters += unique_characters
            reader_overlap_characters += read_characters - unique_characters
            reader_details.append({'task': task, 'label': label, 'calls': r['fresh_model_calls'],
                                   'reads': len(rr['reads']), 'exact_duplicate_reads_after_first': duplicate_reads,
                                   'read_characters': read_characters,
                                   'unique_read_characters': unique_characters,
                                   'overlap_characters': read_characters - unique_characters,
                                   'format_error_count': len(rr['format_errors']),
                                   'path': relative(folder / 'reader-report.json')})
            trace(folder / 'trace.jsonl', phase, task, label)
        if metrics.get('missing_usage_calls'):
            metrics_missing_calls.append({'task': task, 'phase': phase, 'label': label,
                                           'missing_usage_calls': metrics['missing_usage_calls'],
                                           'failed_calls': metrics.get('failed_calls'),
                                           'known_prompt_tokens': metrics.get('known_prompt_tokens'),
                                           'known_completion_tokens': metrics.get('known_completion_tokens'),
                                           'report_path': relative(p if phase == 'feedback' else folder / ('agent/report.json' if phase == 'candidate' else 'report.json'))})
    task_details.append(details)

start = dt.datetime.fromisoformat(launcher['started_at'].replace('Z', '+00:00'))
end = dt.datetime.fromisoformat(controller['ended_at'])
seconds = (end - start).total_seconds()
complete_tasks_lower_bound = sum(r['usage']['tokens'] or 0 for r in rows.values())
complete_phases_lower_bound = sum(x['complete_phase_tokens_minimum'] for x in by_phase.values())
native_known_lower_bound = sum(c['input'] + c['output'] for c in native_tokens_by_phase.values())
for phase, vals in by_phase.items():
    vals['native_known_input_tokens'] = native_tokens_by_phase[phase]['input']
    vals['native_known_output_tokens'] = native_tokens_by_phase[phase]['output']
    vals['native_known_total_tokens_minimum'] = vals['native_known_input_tokens'] + vals['native_known_output_tokens']
    vals['native_events'] = dict(native_tokens_by_phase[phase])
    vals['input_token_frequency_top10'] = input_frequency[phase].most_common(10)
    vals['request_estimates'] = describe(request_estimates_by_phase[phase])
    vals['llm_call_duration_seconds'] = describe(call_seconds_by_phase[phase])
    vals['share_of_known_native_tokens_minimum'] = vals['native_known_total_tokens_minimum'] / native_known_lower_bound

result = {
    'schema': 'harness2-cost-analysis-v1',
    'source': relative(SOURCE),
    'source_sha256': {name: sha(SOURCE / name) for name in ('report.json', 'comparison.json', 'controller.json', 'launcher.json')},
    'operations': {'model_calls': 0, 'network_calls': 0, 'test_executions': 0, 'runtime_changes': 0},
    'definitions': {
        'official_minimum': 'Sum task usage.tokens only for tasks with complete phase usage; matches comparison.known_tokens_minimum. Whole task dropped from this sum when one phase is unknown.',
        'phase_minimum': 'Sum numeric usage.phases[].tokens over all tasks, including known phases of tasks with incomplete totals.',
        'native_minimum': 'Sum input/output of every llm_finished or llm_failed trace event with integer native counts and usage_known != false; each phase folder once. Unknown events remain unknown, never zero.',
        'feedback_nochange': 'Round has candidate_hash_before and identical candidate_hash after; no claim about correctness or server nondeterminism.',
        'candidate_exact_duplicate_actions': 'Subsequent identical action+canonical JSON arguments within one rollout; status-independent, not semantic/context duplicate.',
        'reader_overlap': 'Within each editor and same path+SHA, total requested [offset,end) characters minus interval union coverage. Excludes preloaded packet; counts overlapping evidence reads, not tokens.',
        'request_estimate': 'Executor heuristic estimate, not exact tokenizer measurement; exceeding declared context is a risk signal, not proof of server truncation.',
        'duration': 'Launcher-to-controller-end is actual wall time. Per-task result.seconds excludes launch preparation/final grading; phase/call durations can overlap in parallel probes and must not be added as wall time.',
        'comparison': 'Historical original 24/50 and old Harness2 27/50 are reused full 50 rows, not rerun. New arm 25/50. Original has unknown usage, so no exact Token-cost ratio is available.',
    },
    'summary': {
        'tasks': 50, 'resolved': 25, 'full_ppc_completed': 50,
        'rollouts': len(candidate_details), 'editors': len(reader_details),
        'model_calls': sum(row['usage']['fresh_model_calls'] for row in rows.values()),
        'wall_seconds': seconds, 'wall_hours': seconds / 3600,
        'task_runtime_seconds': describe([row['result']['seconds'] for row in rows.values()]),
        'task_calls': describe([row['usage']['fresh_model_calls'] for row in rows.values()]),
        'official_known_tokens_minimum': complete_tasks_lower_bound,
        'phase_complete_tokens_minimum': complete_phases_lower_bound,
        'native_known_tokens_minimum': native_known_lower_bound,
        'actual_total_tokens': None,
        'unknown_task_total_count': sum(row['usage']['tokens'] is None for row in rows.values()),
        'unknown_phase_total_count': len(unknown_phases),
        'missing_native_usage_event_count': len(missing_native_calls),
        'metrics_missing_usage_calls': sum(x['missing_usage_calls'] for x in metrics_missing_calls),
        'feedback_rounds': sum(feedback_rounds), 'feedback_nochange_rounds': feedback_nochange_count,
        'feedback_nochange_known_tokens_minimum': feedback_nochange_known_tokens,
        'feedback_rejected_rounds': feedback_rejected_count,
        'feedback_rejected_known_tokens_minimum': feedback_rejected_known_tokens,
        'feedback_applied_but_unchanged_rounds': feedback_applied_no_change,
        'feedback_revisiting_prior_hash_after_first': feedback_repeated_state_count,
        'feedback_limit_reached_rollouts': feedback_attempts_by_limit,
        'feedback_round_distribution': describe(feedback_rounds),
        'feedback_round_seconds': describe(feedback_round_time),
        'reader_exact_duplicate_reads_after_first': reader_exact_duplicate_reads,
        'reader_total_requested_characters': reader_read_characters,
        'reader_unique_requested_characters': reader_unique_characters,
        'reader_overlap_requested_characters': reader_overlap_characters,
    },
    'by_phase': {k: dict(v) for k, v in by_phase.items()},
    'candidate_statuses': dict(candidate_status),
    'candidate_action_statuses': dict(candidate_action_status),
    'candidate_action_names': dict(candidate_action_names),
    'candidate_exact_duplicate_actions': dict(candidate_duplicate_names),
    'feedback_statuses': dict(feedback_status),
    'feedback_patch_statuses': dict(patch_status),
    'feedback_patch_error_codes': dict(patch_codes),
    'reader_format_errors': dict(reader_format_errors),
    'blocked_validation_records': blocked_validation_records,
    'blocked_validation_infrastructure_errors': dict(collections.Counter(x['infrastructure_error'] for x in blocked_validation_records)),
    'top_tasks_by_seconds': sorted(task_details, key=lambda d: d['seconds'], reverse=True)[:10],
    'top_tasks_by_feedback_rounds': sorted(task_details, key=lambda d: d['feedback_rounds'], reverse=True)[:10],
    'top_editors_by_overlap': sorted(reader_details, key=lambda d: d['overlap_characters'], reverse=True)[:10],
    'task_details': task_details,
    'feedback_details': feedback_details,
    'candidate_details': candidate_details,
    'reader_details': reader_details,
    'unknown_phases': unknown_phases,
    'metrics_missing_calls': metrics_missing_calls,
    'missing_native_usage_events': missing_native_calls,
    'traces': trace_facts,
}
assert result['summary']['model_calls'] == comparison['fresh_model_calls'] == 3417
assert complete_tasks_lower_bound == comparison['known_tokens_minimum'] == 30859536
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'cost-analysis.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({k: result[k] for k in ('summary', 'by_phase', 'candidate_statuses', 'feedback_statuses', 'feedback_patch_statuses', 'feedback_patch_error_codes')}, ensure_ascii=False, indent=2))
