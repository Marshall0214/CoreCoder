"""Trace the public prompt definition acquisition gap without model or hidden-test access."""

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.read_policy import BoundedReadTool
from evals.real_admission import DATA
from evals.real_suite import file_hash
from evals.runtime import Events
from evals.schema import RunConfig, relative_path
from evals.staged_repair import validate_localization
from evals.symbol_context import symbol_evidence

TASK = 'click-prompt-suffix'
SOURCE = 'src/click/termui.py'
SYMBOL = 'prompt'


def returned_lines(response, source):
    """Validate numbered lines against source; footer text is not evidence."""
    lines = source.splitlines()
    result = []
    for row in response.splitlines():
        prefix, separator, text = row.partition('\t')
        if separator and prefix.isdigit():
            number = int(prefix)
            if not 1 <= number <= len(lines) or text != lines[number - 1]:
                raise ValueError('Returned source line is truncated or differs from original')
            if result and number != result[-1] + 1:
                raise ValueError('Read response is not contiguous')
            result.append(number)
    return result


def read_history(events, source, path):
    reads, pending, shown = [], None, set()
    for event in events:
        if event['event'] == 'tool_started' and event['tool'] == 'read_file':
            if pending is not None:
                raise ValueError('Overlapping read events cannot be paired')
            pending = event
        elif event['event'] == 'tool_finished' and event['tool'] == 'read_file':
            if pending is None:
                raise ValueError('Read completion has no request')
            request = pending
            pending = None
            if request['arguments']['file_path'].replace('\\', '/') != path:
                continue
            lines = returned_lines(event['result'], source)
            reads.append({'request_sequence': request['sequence'], 'response_sequence': event['sequence'],
                          'arguments': request['arguments'], 'returned_start': min(lines) if lines else None,
                          'returned_end': max(lines) if lines else None, 'returned_lines': len(lines),
                          'new_lines': len(set(lines) - shown), 'duplicate_lines': len(set(lines) & shown),
                          'response_chars': len(event['result']),
                          'continuation': event['result'].splitlines()[-1] if '[bounded read;' in event['result'] else None,
                          'response': event['result']})
            shown.update(lines)
    if pending is not None:
        raise ValueError('Incomplete read event')
    return reads


def definition(source, name):
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(functions) != 1:
        raise ValueError('Expected a unique public top-level definition')
    node = functions[0]
    return {'start': node.lineno, 'end': node.end_lineno, 'lines': node.end_lineno - node.lineno + 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True, help='Original TASK/before directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((DATA / 'staged-shared-repeat-v1.json').read_text(encoding='utf-8'))
    record = protocol['checkpoints'][TASK]
    checkpoint_path = ROOT / relative_path(record['path'])
    if file_hash(checkpoint_path) != record['sha256']:
        raise ValueError('Frozen checkpoint changed')
    checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
    config = RunConfig(**checkpoint['config'])
    workspace, output = args.source_root.resolve(), args.output.resolve()
    if output.exists() or output.is_relative_to(workspace) or output.is_relative_to(checkpoint_path.parent.resolve()):
        raise ValueError('Use a fresh output outside frozen source and localization')
    validate_localization(checkpoint, workspace, checkpoint['description'], checkpoint['allowed_files'], config)
    source_path = workspace / SOURCE
    source = source_path.read_text(encoding='utf-8')
    target = definition(source, SYMBOL)
    trace_path = checkpoint_path.parent / 'trace.jsonl'
    events = [json.loads(line) for line in trace_path.read_text(encoding='utf-8').splitlines()]
    reads = read_history(events, source, SOURCE)
    tool = BoundedReadTool()
    for row in reads:
        replay = tool.execute(str(source_path), row['arguments'].get('offset', 1), row['arguments'].get('limit', 120))
        if replay != row.pop('response'):
            raise ValueError('Original read response cannot be reproduced')
    output.mkdir(parents=True, exist_ok=False)
    replay_events = Events(output / 'seed-replay.jsonl', 'offline-seed-replay')
    seeds = symbol_evidence(workspace, checkpoint['description'], checkpoint['allowed_files'], replay_events,
                            max_chars=config.search_max_chars, top_k=config.evidence_top_k,
                            depth=config.evidence_dependency_depth, index_mode='symbols', query_policy='identifiers',
                            packing_policy='dependency-reserve', dependency_scope='full-seed')
    if seeds != checkpoint['pool']['seeds']:
        raise ValueError('Frozen seed candidates cannot be reproduced')
    built = next(event for event in events if event['event'] == 'symbol_evidence_built')
    rebuilt = json.loads(replay_events.path.read_text(encoding='utf-8').splitlines()[-1])
    if any(built[key] != rebuilt[key] for key in ('seeds', 'selected', 'discarded', 'seed_limit', 'seed_chars')):
        raise ValueError('Seed provenance differs from original trace')
    complete_response = tool.execute(str(source_path), target['start'], target['lines'])
    complete_lines = returned_lines(complete_response, source)
    (output / 'definition-read.txt').write_text(complete_response, encoding='utf-8')
    pool = checkpoint['pool']['reads'] + checkpoint['pool']['seeds']
    covered = {line for row in pool if row['path'] == SOURCE
               for line in range(row['start_line'], row['end_line'] + 1)}
    report = {'purpose': 'offline-public-definition-acquisition-audit-v1', 'task_id': TASK,
              'model_calls': 0, 'live_localizations': 0, 'grader_calls': 0, 'symbol': SYMBOL,
              'source_path': SOURCE, 'source_sha256': file_hash(source_path), 'definition': target,
              'checkpoint_sha256': file_hash(checkpoint_path), 'trace_sha256': file_hash(trace_path),
              'audit_sha256': file_hash(Path(__file__)), 'reads': reads,
              'missing_definition_lines': sorted(set(range(target['start'], target['end'] + 1)) - covered),
              'seed_replay_matches': True, 'seed_limit_chars': built['seed_limit'],
              'seed_prompt_discard': [row for row in built['discarded'] if row['symbol'] == SYMBOL and row['path'] == SOURCE],
              'budget_stops': [{k: v for k, v in event.items() if k not in {'time', 'run_id'}}
                               for event in events if event['event'] == 'budget_blocked'],
              'localization_stages': checkpoint['localization_result']['stages'],
              'definition_read': {'returned_start': min(complete_lines), 'returned_end': max(complete_lines),
                                   'returned_lines': len(complete_lines), 'response_chars': len(complete_response),
                                   'complete': complete_lines == list(range(target['start'], target['end'] + 1))},
              'limitations': 'Offline deterministic retrieval and tool replay only. No success or live token-cost claim; '
                             'full definition still competes with other evidence under the original packing cap.'}
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
