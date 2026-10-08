"""Replace low-ranked seeds using failed public-test execution, within old limits."""
import ast
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from unittest.mock import patch

from docs.experiments import frozen_feedback_v1 as guarded
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot
from evals.symbol_context import dependency_refs

previous = guarded.previous
PROBE = Path(__file__).with_name('failure_trace_probe_v1.py')


def probe(workspace, job, root):
    before = digest(snapshot(workspace))
    harness = Path(job['harness'])
    if digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Public harness changed')
    root.mkdir()
    results = []
    for group in ('Reproduce', 'Preserve'):
        destination = root / (group + '.json')
        process = run_process([sys.executable, '-I', '-B', str(PROBE), str(workspace), job['source_root'],
                               str(harness), job['package'], group, json.dumps(job['allowed_files']), str(destination)],
                              workspace, 15, root / (group + '.stdout.txt'), root / (group + '.stderr.txt'),
                              test_environment(workspace))
        data = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
        usable = (process['returncode'] == 0 and not process['timed_out'] and data.get('tests_run', 0) > 0
                  and len(data.get('records', [])) == data.get('tests_run')
                  and not any(data.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes'))
                  and not any(r['truncated'] for r in data.get('records', [])))
        results.append({'group': group, 'usable': bool(usable), 'process': process, 'data': data})
    if before != digest(snapshot(workspace)) or digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Probe mutated source or public checks')
    return results


def select(workspace, allowed, seeds, observations, original_workspace=None):
    fallback = previous.refresh_seeds(workspace, allowed, seeds)
    records = [r for group in observations for r in group.get('data', {}).get('records', [])]
    if not observations or not all(g['usable'] for g in observations) or not any(not r['passed'] for r in records):
        fallback['metadata']['policy'] = 'failure-context-fallback'
        return fallback
    index = previous.baseline.functions.FunctionIndex(workspace, allowed)
    index.refresh()
    chunks = {(c.path, index.names[(c.path, c.start_line, c.end_line)]): c for c in index.chunks}

    def resolve(item):
        path, line, name = item
        matches = [(k, c) for k, c in chunks.items() if k[0] == path and k[1].rsplit('.', 1)[-1] == name
                   and c.start_line <= line <= c.end_line]
        return min(matches, key=lambda x: x[1].end_line - x[1].start_line)[0] if matches else None

    failed, passed, exceptions, neighbors = Counter(), Counter(), Counter(), Counter()
    graph = defaultdict(set)

    def connect(a, b):
        graph[a].add(b)
        graph[b].add(a)
    for record in records:
        hits = set()
        for row in record['functions']:
            key = resolve((row['path'], row['line'], row['name']))
            if key:
                hits.add(key)
                if not record['passed'] and row['exception_lines']:
                    exceptions[key] += 1
        (passed if record['passed'] else failed).update(hits)
    for record in records:
        if record['passed']:
            continue
        for caller, callee in record['edges']:
            a, b = resolve(caller), resolve(callee)
            if a and b:
                neighbors.update((a, b))
                connect(a, b)
    for key in failed:
        c = chunks[key]
        for other, name in dependency_refs(index.parsed[c.path], c.start_line, c.end_line, key[1]):
            target = (other or c.path, name)
            if target in chunks and target != key:
                neighbors[target] += 1
                connect(key, target)
    original = [(r['path'], r['symbol']) for r in fallback['evidence']]
    changed = []
    if original_workspace is not None:
        before = previous.baseline.functions.FunctionIndex(original_workspace, allowed)
        before.refresh()
        for key in original:
            node = index.parsed[key[0]]['symbols'][key[1]][2]
            old = before.parsed.get(key[0], {}).get('symbols', {}).get(key[1])
            if old is None or ast.dump(node) != ast.dump(old[2]):
                changed.append(key)
    distance = dict.fromkeys(original, 0)
    queue = deque(original)
    while queue:
        key = queue.popleft()
        if distance[key] >= 2:
            continue
        for target in sorted(graph[key]):
            if target not in distance:
                distance[target] = distance[key] + 1
                queue.append(target)
    order = sorted(set(failed) | set(neighbors), key=lambda k: (distance.get(k, 99),
                   -failed[k] / max(1, failed[k] + passed[k]), -exceptions[k], -int(k in failed), -neighbors[k], k))
    # Keep two original anchors; remaining capacity goes to executed functions
    # and resolvable direct dependencies. Execution is evidence, not fault proof.
    near = [k for k in order if distance.get(k, 99) <= 2 and k not in original]
    far = [k for k in order if k not in near]
    ordered = list(dict.fromkeys(original[:2] + changed + near + original[2:] + far))
    packed = previous.baseline.functions.pack(index, [(failed[k] / max(1, failed[k] + passed[k]), chunks[k])
                                                      for k in ordered if k in chunks], limit=6000, top_k=5)
    for row in packed['evidence']:
        key = (row['path'], row['symbol'])
        row['reason'] = ('retained_anchor' if key in original[:2] else
                         'retained_modified_function' if key in changed else
                         'failed_public_execution' if key in failed else 'execution_neighbor' if key in neighbors else 'original_seed')
    packed['metadata'].update(policy='failure-context-v1', failed_tests=sum(not r['passed'] for r in records),
                              ranking='two anchors and modified functions; <=2-hop execution/static neighborhood; failed test incidence; exceptions; original seeds before distant helpers',
                              modified_symbols=changed,
                              original_symbols=original, executed_candidates=[{'path': k[0], 'symbol': k[1],
                              'failed_tests': failed[k], 'passed_tests': passed[k], 'anchor_distance': distance.get(k)} for k in order],
                              limits='Call incidence and conservative static refs, not SBFL or confirmed root causes; no locals captured')
    previous.repair.validate_evidence(workspace, allowed, packed['evidence'])
    return packed


def run_candidate(llm, job, events):
    root = events.path.parent
    original_refresh = previous.refresh_seeds

    def refresh(workspace, allowed, seeds):
        observations = probe(workspace, job, root / 'failure-probe')
        # select() uses the baseline refresh; temporarily restore it to avoid recursion.
        with patch.object(previous, 'refresh_seeds', original_refresh):
            packed = select(workspace, allowed, seeds, observations, root / 'original-workspace')
        previous.write_json(root / 'failure-context.json', packed)
        events.emit('failure_context_selected', **packed['metadata'])
        return packed

    # One owned worker process, scoped replacement restored even on exceptions.
    # First request, feedback text, validation, rollback and call budget unchanged.
    with patch.object(previous, 'refresh_seeds', refresh):
        return guarded.run_candidate(llm, job, events)
