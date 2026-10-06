"""Development-only budget sensitivity matrix and actual first-source-change accounting."""

import argparse
import json
from pathlib import Path

from .real_admission import DATA
from .real_suite import file_hash, load_manifest, prepare, run_suite
from .schema import RunConfig, relative_path


def first_change_stats(trace):
    spent, known, missing, calls, round_number, reads = 0, 0, 0, 0, None, 0
    reservations = {}
    next_reservation = 0
    partial_lines = 0
    first = None
    for line in trace.read_text(encoding='utf-8').splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            partial_lines += 1
            continue
        kind = event['event']
        if kind == 'agent_round':
            round_number = event['round']
        elif kind == 'request_preflight':
            next_reservation = event['reservation']
        elif kind == 'llm_started':
            reservations[event['call_id']] = next_reservation
        elif kind == 'llm_finished':
            calls += 1
            if event['usage_known']:
                tokens = event['prompt_tokens'] + event['completion_tokens']
                known += tokens
                spent += tokens
            else:
                missing += 1
                spent += reservations[event['call_id']]
        elif kind == 'tool_started' and event['tool'] == 'read_file':
            reads += 1
        elif kind == 'source_changed' and first is None:
            first = {'path': event['path'], 'tool': event['tool'], 'agent_round': round_number,
                     'llm_calls': calls, 'read_calls': reads,
                     'known_tokens': known if calls else None,
                     'budget_accounted_tokens': spent if calls else None,
                     'missing_usage_calls': missing, 'sequence': event['sequence']}
    return {'first_source_change': first, 'total_agent_rounds': round_number,
            'total_read_calls': reads, 'partial_trace_lines': partial_lines,
            'measurement': 'actual byte changes, not attempted edits or final net diff; input plus output tokens'}


def run_diagnostic(protocol, admissions, output, mode='live'):
    data = json.loads(protocol.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or data.get('purpose') != 'development-budget-diagnosis':
        raise ValueError('Expected a development budget diagnostic protocol')
    budgets = data['budgets']
    if (not budgets or any(type(value) is not int or value < 1 for value in budgets)
            or budgets != sorted(set(budgets))):
        raise ValueError('Budgets must be positive, unique and increasing')
    suite = protocol.parent / relative_path(data['suite'])
    if file_hash(suite) != data['suite_sha256']:
        raise ValueError('Diagnostic suite changed')
    output = output.resolve()
    manifest, entries = load_manifest(suite)
    if type(data['repeat']) is not int or not 1 <= data['repeat'] <= 10:
        raise ValueError('Repeat must be between 1 and 10')
    for budget in budgets:
        RunConfig(**dict(manifest['config'], mode=mode, token_budget=budget,
                         max_rounds=data['max_rounds'], wall_timeout=data['wall_timeout']))
    prepared = prepare(entries, admissions)
    for case in prepared:
        if any(output.is_relative_to(path.resolve()) for path in (case[2], case[3])):
            raise ValueError('Diagnostic output must stay outside source and checks')
    # Reuse suite validation before any model calls; each budget gets a fresh suite directory.
    output.mkdir(parents=True, exist_ok=False)
    result = {'purpose': data['purpose'], 'benchmark_eligible': False,
              'protocol': data, 'protocol_sha256': file_hash(protocol), 'mode': mode,
              'expected_runs': len(entries) * data['repeat'] * len(budgets),
              'complete': False, 'groups': []}

    def save():
        result['completed_runs'] = sum(len(group['rows']) for group in result['groups'])
        (output / 'diagnostic.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for budget in budgets:
        report = run_suite(suite, admissions, output / f'budget-{budget}', mode, repeat=data['repeat'],
                           diagnostic_overrides={'token_budget': budget, 'max_rounds': data['max_rounds'],
                                                 'wall_timeout': data['wall_timeout']})
        rows = []
        for row in report['runs']:
            stats = first_change_stats(Path(row['artifacts']) / 'trace.jsonl')
            rows.append({'task_id': row['task_id'], 'repetition': row['repetition'],
                         'status': row['status'], 'accepted': row['accepted'],
                         'metrics': row['metrics'], 'seconds': row['seconds'],
                         'artifacts': row['artifacts'],
                         'changed_files': (row.get('verification') or {}).get('changed_files'), **stats})
        result['groups'].append({'token_budget': budget, 'complete': report['complete'],
                                 'implementation': report['implementation'],
                                 'config': report['config'], 'rows': rows})
        save()
        if not report['complete']:
            return result
    result['complete'] = True
    save()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=DATA / 'budget-diagnostic-v1.json')
    parser.add_argument('--admission', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('live', 'scripted'), default='live')
    args = parser.parse_args()
    admissions = {}
    for value in args.admission:
        name, separator, path = value.partition('=')
        if not separator or not path or name in admissions:
            parser.error('Admissions must be unique SOURCE=PATH entries')
        admissions[name] = Path(path).resolve()
    if args.mode == 'live':
        from corecoder.config import _load_dotenv

        _load_dotenv()
    result = run_diagnostic(args.protocol.resolve(), admissions, args.output, args.mode)
    print(args.output.resolve() / 'diagnostic.json')
    # A diagnostic completes even if every attempted repair fails.
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
