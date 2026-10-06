"""Offline request/patch provenance audit and public API probes; no model or grader calls."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docs.experiments.staged_compact_packing_v1 import docstring_ranges
from docs.experiments.staged_evidence_coverage_v1 import covered_lines
from evals.process import run_process
from evals.real_suite import file_hash
from evals.schema import relative_path
from evals.staged_repair import object_hash
from evals.symbol_context import apply_symbol_patch

TASKS = {'click-invoke-missing': 'expansion', 'click-resource-exception': 'original',
         'click-prompt-suffix': 'expansion'}

PROBE = '''import json
import click
from click import termui

if TASK == "click-invoke-missing":
    command = click.Command("probe", params=[click.Option(["--items"], multiple=True)], callback=lambda items: items)
    with click.Context(click.Command("root")) as ctx:
        value = ctx.invoke(command)
    result = {"omitted_multiple_value": repr(value), "value_type": type(value).__name__}
else:
    result = {}
    for name in ("prompt", "confirm"):
        for suffix in ("", ": "):
            writes = []
            termui.echo = lambda text=None, **kwargs: writes.append(str(text) if text is not None else "")
            def input_func(text):
                writes.append(text)
                return "yes" if name == "confirm" else "value"
            termui.visible_prompt_func = input_func
            getattr(click, name)("Label", prompt_suffix=suffix, show_default=False)
            result[name + ":" + repr(suffix)] = "".join(writes)
print(json.dumps(result))
'''


def edit_provenance(edit, sources, fragments, removed):
    name = edit['file']
    text = sources[name].decode('utf-8').replace('\r\n', '\n')
    old = edit['old']
    without_docs = ''.join(line for number, line in enumerate(text.splitlines(keepends=True), 1)
                           if number not in set(removed.get(name, [])))
    full_count = text.count(old)
    visible = any(row['path'] == name and old in row['content'] for row in fragments)
    return {'file': name, 'old_sha256': hashlib.sha256(old.encode()).hexdigest(),
            'old_full_matches': full_count, 'old_in_single_fragment': visible,
            'matches_only_after_doc_removal': full_count == 0 and old in without_docs,
            'old_chars': len(old), 'new_chars': len(edit['new'])}


def delta(sources, baseline, compact):
    result = []
    for path in sorted({row['path'] for row in baseline + compact}):
        ranges, _ = docstring_ranges(sources[path])
        docs = {line for start, end in ranges for line in range(start, end + 1)}
        a, b = covered_lines(baseline, path), covered_lines(compact, path)
        result.append({'path': path, 'lost_docstring_lines': sorted((a - b) & docs),
                       'lost_other_lines': sorted((a - b) - docs),
                       'gained_docstring_lines': sorted((b - a) & docs),
                       'gained_other_lines': sorted((b - a) - docs)})
    return result


def validate_candidate(workspace, sources, fragments, response, status):
    """Reapply the recorded patch in scratch files; reject changed probe inputs."""
    with tempfile.TemporaryDirectory(prefix='staged-audit-', dir=ROOT / '.tmp') as directory:
        scratch = Path(directory)
        for name, raw in sources.items():
            path = scratch / relative_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        rejected = False
        try:
            apply_symbol_patch(response, scratch, list(sources), fragments)
        except (ValueError, TypeError, KeyError):
            rejected = True
        if rejected != (status == 'invalid_patch'):
            raise ValueError('Recorded patch status cannot be reproduced')
        for name in sources:
            actual = workspace / relative_path(name)
            if actual.is_symlink() or actual.read_bytes() != (scratch / name).read_bytes():
                raise ValueError('Candidate source differs from recorded patch')
    return True


def public_probe(workspace, task, output):
    output.mkdir(parents=True, exist_ok=False)
    script = output / 'probe.py'
    script.write_text('TASK = ' + repr(task) + '\n' + PROBE, encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(workspace / 'src'), PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    execution = run_process([sys.executable, str(script)], workspace, 15,
                            output / 'stdout.txt', output / 'stderr.txt', env)
    if execution['timed_out'] or execution['returncode'] != 0:
        return {'execution': execution, 'result': None}
    return {'execution': execution, 'result': json.loads((output / 'stdout.txt').read_text(encoding='utf-8'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--source', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for item in args.source:
        name, separator, path = item.partition('=')
        if not separator or not path or name in roots:
            parser.error('Supply unique SOURCE=PATH directories')
        roots[name] = Path(path).resolve()
    if set(roots) != set(TASKS.values()):
        raise ValueError('This audit requires original and expansion before-source directories')
    experiment = json.loads(args.experiment.read_text(encoding='utf-8'))
    analysis = json.loads((args.experiment.parent / 'analysis.json').read_text(encoding='utf-8'))
    if not experiment['complete'] or analysis['experiment_sha256'] != file_hash(args.experiment):
        raise ValueError('Expected the unchanged complete analyzed experiment')
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(path) for path in [*roots.values(), args.experiment.parent.resolve()]):
        raise ValueError('Use a fresh audit directory outside sources and experiment')
    audits = []
    # Validate all six requests and source versions before executing any probe.
    for task, group in TASKS.items():
        rows = [row for row in experiment['patch_runs'] if row['task_id'] == task]
        if len(rows) != 2 or {row['policy'] for row in rows} != {'read-first', 'compact-read-first-v1'}:
            raise ValueError('Missing audited branch')
        request_fragments, branches, sources = {}, [], {}
        for row in rows:
            artifacts = Path(row['artifacts'])
            request = artifacts / 'patch-request.json'
            response = artifacts / 'staged-patch-response.txt'
            messages = json.loads(request.read_text(encoding='utf-8'))
            payload = json.loads(messages[1]['content'])
            if (object_hash(messages) != row['worker']['patch_prompt_hash']
                    or object_hash(payload['fragments']) != row['worker']['evidence_hash']):
                raise ValueError('Recorded request changed')
            record = experiment['protocol']['checkpoints'][task]
            checkpoint_path = ROOT / relative_path(record['path'])
            if file_hash(checkpoint_path) != record['sha256']:
                raise ValueError('Checkpoint changed')
            checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
            if payload['description'] != checkpoint['description']:
                raise ValueError('Public description changed')
            sources = {name: (roots[group] / task / 'before' / relative_path(name)).read_bytes()
                       for name in payload['allowed_files']}
            if {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()} != checkpoint['source_hashes']:
                raise ValueError('Original source versions changed')
            response_text = response.read_text(encoding='utf-8')
            edits = json.loads(response_text)['edits']
            candidate_verified = validate_candidate(artifacts / 'workspace', sources, payload['fragments'],
                                                     response_text, row['worker']['status'])
            removed = (row['worker'].get('packing') or {}).get('removed_docstring_lines', {})
            branches.append({'policy': row['policy'], 'status': row['status'], 'request_sha256': file_hash(request),
                             'response_sha256': file_hash(response), 'artifacts': str(artifacts),
                             'candidate_matches_recorded_patch': candidate_verified,
                             'edits': [edit_provenance(edit, sources, payload['fragments'], removed) for edit in edits],
                             'model_error': row['worker'].get('error')})
            request_fragments[row['policy']] = payload['fragments']
        audits.append({'task_id': task, 'description': checkpoint['description'], 'branches': branches,
                       'evidence_delta': delta(sources, request_fragments['read-first'], request_fragments['compact-read-first-v1'])})
    output.mkdir(parents=True, exist_ok=False)
    for audit in audits:
        task = audit['task_id']
        if task == 'click-resource-exception':
            continue  # Invalid-patch provenance is diagnosed without executing rejected edits.
        audit['original_public_probe'] = public_probe(roots[TASKS[task]] / task / 'before', task, output / task / 'original')
        for row in audit['branches']:
            row['public_probe'] = public_probe(Path(row['artifacts']) / 'workspace', task, output / task / row['policy'])
    report = {'purpose': 'offline-public-failure-audit-v1', 'model_calls': 0, 'grader_calls': 0,
              'experiment_sha256': file_hash(args.experiment), 'audit_sha256': file_hash(Path(__file__)),
              'tasks': audits, 'limitations': 'Post-hoc public probes are diagnostic witnesses, not held-out scores. '
              'Evidence deltas do not isolate why the model selected a different patch. No hidden tests or reference fixes read.'}
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
