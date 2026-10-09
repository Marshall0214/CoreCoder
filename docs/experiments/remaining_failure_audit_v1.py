"""Offline audit of the frozen comparison's failed full-workflow candidates."""
import argparse
import ast
import difflib
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from docs.experiments import system_comparison_v1 as baseline
from evals.runner import digest, snapshot

FRAME = re.compile(r'File "([^"]+)", line (\d+), in ([^\n]+)')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changed_ranges(before, after):
    """Candidate coordinates; deletion has an explicit zero-width boundary."""
    return [{'kind': tag, 'before': [a + 1, b], 'candidate': [c + 1, d]}
            for tag, a, b, c, d in difflib.SequenceMatcher(
                None, before.splitlines(), after.splitlines(), autojunk=False).get_opcodes()
            if tag != 'equal']


def frame_facts(log, runtime, candidate, read):
    facts = []
    for name, number, function in FRAME.findall(log):
        path = Path(name)
        if not path.is_absolute() or not path.resolve().is_relative_to(runtime.resolve()):
            continue
        relative = path.resolve().relative_to(runtime.resolve())
        target = candidate / relative
        if not target.is_file() or target.is_symlink():
            raise ValueError('Missing owned candidate frame')
        source = read(target)
        lines = source.splitlines()
        line = int(number)
        if not 1 <= line <= len(lines):
            raise ValueError('Traceback outside candidate snapshot')
        facts.append({'file': relative.as_posix(), 'line': line, 'function': function.strip(),
                      'statement': lines[line - 1].strip(), 'candidate_sha256': sha(target)})
    # The last owned frame can precede a user callback frame in the public harness.
    return facts


def edited_symbols(source, ranges):
    result = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                c['candidate'][0] <= node.end_lineno and c['candidate'][1] >= node.lineno
                for c in ranges if c['kind'] != 'delete'):
            result.append({'name': node.name, 'line': node.lineno, 'end_line': node.end_lineno})
    return result


def signature(worker):
    if worker['initial']['status'] != 'completed':
        return 'initial_' + worker['initial']['status']
    if worker.get('correction', {}).get('status') != 'completed':
        return 'correction_' + worker.get('correction', {}).get('status', 'missing')
    groups = worker['correction_checks']['public']
    target, preserve = groups['Reproduce']['passed'], groups['Preserve']['passed']
    if target and not preserve:
        return 'target_pass_preserve_fail'
    if not target and not preserve:
        return 'target_and_preserve_fail'
    if not target and preserve:
        return 'target_fail_preserve_pass'
    return 'public_pass_frozen_rejection'


def audit(source):
    manifest = baseline.load(source / 'manifest.json')
    baseline.intact(manifest)
    hashes = {}

    def read(path):
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('Audit input outside frozen experiment')
        hashes[str(path.resolve())] = sha(path)
        return path.read_text(encoding='utf-8')

    experiment = json.loads(read(source / 'experiment.json'))
    rows = [r for r in experiment['runs'] if r['policy'] == 'full']
    if not experiment['complete'] or len(rows) != 50 or len({r['task_id'] for r in rows}) != 50:
        raise ValueError('Require complete unique 50-task comparison')
    failures = [r for r in rows if not r['accepted']]
    if len(failures) != 18:
        raise ValueError('Unexpected frozen failure count')
    cases = []
    for row in failures:
        task = row['task_id']
        if not re.fullmatch(r'[a-z0-9-]+', task):
            raise ValueError('Invalid task id')
        root = source / 'runs' / task / 'full'
        job = json.loads(read(root / 'job.json'))
        worker = row['worker']
        if digest(snapshot(root / 'original-workspace')) != job['original_hash']:
            raise ValueError('Original snapshot mismatch')
        case = {'task_id': task, 'historical_split': row['split'],
                'status': worker['status'], 'signature': signature(worker),
                'original_restored': worker['original_restored'], 'stages': []}
        for stage, key, folder in [('initial', 'initial', 'initial-staging'),
                                   ('feedback', 'correction', 'feedback-staging')]:
            outcome = worker.get(key)
            if outcome is None:
                continue
            messages = json.loads(read(root / (stage + '-messages.json')))
            payload = json.loads(messages[-1]['content'])
            evidence = payload['fragments']
            item = {'stage': stage, 'status': outcome['status'], 'error': outcome.get('error'),
                    'evidence_symbols': [f.get('symbol') for f in evidence],
                    'diffs': [], 'logs': [], 'anchors': []}
            response = root / (stage + '-response.txt')
            if not response.exists():
                response = root / ('provider-call-01' if stage == 'initial' else 'provider-call-02') / 'response.txt'
            if response.exists():
                answer = read(response)
                item['response_sha256'] = sha(response)
                try:
                    patch = json.loads(answer)
                except json.JSONDecodeError:
                    patch = {}
                current = root / ('original-workspace' if stage == 'initial' else 'initial-workspace')
                for edit in patch.get('edits', []):
                    name, old = edit.get('file'), edit.get('old')
                    if name not in job['allowed_files'] or not isinstance(old, str) or not old:
                        continue
                    # Counts are relative to stage input, not a partially applied invalid patch.
                    text = read(current / name)
                    item['anchors'].append({'file': name, 'input_occurrences': text.count(old),
                                            'supplied_in_fragment': any(
                                                f['path'] == name and old in f['content'] for f in evidence)})
            if outcome['status'] == 'completed':
                candidate = root / folder
                if stage == 'initial' and snapshot(candidate) != snapshot(root / 'initial-workspace'):
                    raise ValueError('Initial candidate snapshot mismatch')
                for name in job['allowed_files']:
                    if Path(name).is_absolute() or '..' in Path(name).parts:
                        raise ValueError('Invalid allowed file')
                    original = read(root / 'original-workspace' / name)
                    changed = read(candidate / name)
                    ranges = changed_ranges(original, changed)
                    if ranges:
                        item['diffs'].append({'file': name, 'candidate_sha256': sha(candidate / name),
                                              'ranges': ranges, 'symbols': edited_symbols(changed, ranges),
                                              'diff': ''.join(difflib.unified_diff(
                                                  original.splitlines(True), changed.splitlines(True),
                                                  fromfile='original/' + name, tofile='candidate/' + name, n=3))})
                checks = worker['initial_checks' if stage == 'initial' else 'correction_checks']
                prefix = 'initial' if stage == 'initial' else 'corrected'
                for label, groups in checks.items():
                    for group, result in groups.items():
                        if result['passed']:
                            continue
                        path = root / (prefix + '-' + label) / (group + '.stderr.txt')
                        log = read(path)
                        frames = frame_facts(log, root / 'workspace', candidate, read)
                        for frame in frames:
                            diffs = [d for d in item['diffs'] if d['file'] == frame['file']]
                            frame['line_overlaps_change'] = any(
                                c['candidate'][0] <= frame['line'] <= c['candidate'][1]
                                for d in diffs for c in d['ranges'])
                        item['logs'].append({'label': label, 'group': group,
                                             'path': str(path.resolve()), 'sha256': sha(path),
                                             'owned_frames': frames, 'tail': log[-2200:]})
            case['stages'].append(item)
        cases.append(case)
    baseline.intact(manifest)
    if any(sha(Path(p)) != value for p, value in hashes.items()):
        raise ValueError('Audit input changed during read')
    corrections = [s for c in cases for s in c['stages']
                   if s['stage'] == 'feedback' and s['status'] == 'completed']
    return {'complete': True, 'source': str(source.resolve()), 'tasks': 50, 'failures': len(cases),
            'model_calls': 0, 'test_executions': 0, 'baseline_intact': True,
            'complete_corrections': len(corrections),
            'corrections_without_owned_public_frames': sum(
                not any(log['owned_frames'] for log in s['logs'] if log['label'] == 'public')
                for s in corrections),
            'signature_counts': dict(Counter(c['signature'] for c in cases)),
            'limits': ['Retrospective audit, not a new repair experiment',
                       'No reference patch or independent grader code read',
                       'Historical heldout failures now inspected; do not treat as untouched holdout',
                       'Traceback overlap is descriptive, not a necessary repair criterion',
                       'Invalid-stage anchor counts describe stage input, not sequential patch application'],
            'input_hashes': hashes, 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=baseline.BASE / 'system-comparison-v1-rerun')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve().is_relative_to(args.source.resolve()):
        raise ValueError('Require fresh output outside frozen source')
    result = audit(args.source.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['signature_counts'], ensure_ascii=False))
