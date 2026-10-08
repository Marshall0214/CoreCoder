"""Diagnose missing predicate dependencies using only cited buggy-source spans."""
import argparse
import ast
import hashlib
import json
import shutil
import time
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import provider_compare_worker_v1 as adapters
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = guarded.previous


def dependency_evidence(workspace, allowed):
    specs = [('more_itertools/more.py', 'replace', 'full'),
             ('more_itertools/more.py', 'locate', 'full'),
             ('more_itertools/more.py', 'windowed', 'full'),
             ('more_itertools/recipes.py', 'consume', 'body'),
             ('more_itertools/recipes.py', '_marker', 'assignment')]
    rows = []
    for rank, (name, symbol, kind) in enumerate(specs, 1):
        if name not in allowed:
            raise ValueError('Dependency source is outside allowed files')
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError('Dependency source escapes workspace')
        data = path.read_bytes()
        lines = data.decode('utf-8').splitlines(keepends=True)
        tree = ast.parse(data.decode('utf-8'))
        matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == symbol
                   or isinstance(n, ast.Assign) and any(isinstance(a, ast.Name) and a.id == symbol for a in n.targets)]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous dependency symbol')
        node = matches[0]
        start = node.lineno
        if kind == 'body':
            body = node.body
            first = int(isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str))
            start = body[first].lineno
        rows.append({'path': name, 'symbol': symbol, 'start_line': start, 'end_line': node.end_lineno,
                     'content': ''.join(lines[start-1:node.end_lineno]),
                     'content_hash': hashlib.sha256(data).hexdigest(), 'rank': rank, 'score': 6-rank,
                     'reason': 'manual_original_source_dependency_audit', 'complete_symbol': kind == 'full'})
    # If a candidate grows, keep executable windowed code rather than exceeding the same cap.
    if sum(len(r['content']) for r in rows) > 6000:
        row = rows[2]
        tree = ast.parse((workspace / row['path']).read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'windowed')
        first = int(isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str))
        row['start_line'] = node.body[first].lineno
        lines = (workspace / row['path']).read_bytes().decode('utf-8').splitlines(keepends=True)
        row['content'] = ''.join(lines[row['start_line']-1:row['end_line']])
        row['complete_symbol'] = False
    previous.repair.validate_evidence(workspace, allowed, rows)
    return rows


def expanded_candidate(llm, job, events):
    root = events.path.parent
    guarded.validate(job, root)
    workspace = Path(job['workspace'])
    original, initial = root / 'original-workspace', root / 'initial-workspace'
    shutil.copytree(workspace, original)
    result = {'status': 'agent_error', 'feedback_attempts': 0, 'published': False,
              'correction_retained': False, 'protocol': 'dependency-context-v1'}
    try:
        first = previous.request(llm, workspace, job, job['evidence'], root, 'initial')
        result['initial'] = first
        result['initial_metrics'] = dict(llm.metrics())
        shutil.copytree(workspace, initial)
        if first['status'] != 'completed':
            result.update(status=first['status'], feedback_skipped='initial_not_completed')
        else:
            outcomes = guarded.checked(workspace, job, root, 'initial')
            result['initial_checks'] = outcomes
            selected = outcomes
            if not guarded.valid(outcomes) and guarded.executable(outcomes):
                evidence = dependency_evidence(workspace, job['allowed_files'])
                observation = guarded.feedback(outcomes, workspace, job, root)
                result['feedback_attempts'] = 1
                second = previous.request(llm, workspace, job, evidence, root, 'feedback', observation)
                result['correction'] = second
                if second['status'] == 'completed':
                    corrected = guarded.checked(workspace, job, root, 'corrected')
                    result['correction_checks'] = corrected
                    result['correction_retained'] = guarded.valid(corrected)
                    if result['correction_retained']:
                        selected = corrected
                if not result['correction_retained']:
                    guarded.restore(workspace, initial, root)
                    events.emit('frozen_correction_rejected', initial_restored=True)
            else:
                result['feedback_skipped'] = 'checks_passed' if guarded.valid(outcomes) else 'public_execution_failure'
            result['final_checks'] = selected
            # Recheck immutable guards after generation, including the keep-initial path.
            for name in ('harness', 'frozen_harness'):
                if digest(snapshot(Path(job[name]))) != job[name + '_hash']:
                    raise ValueError('Certified public harness changed')
            result['published'] = guarded.valid(selected)
            result['status'] = 'completed' if result['published'] else 'failed_public_validation'
    except Exception as exc:  # noqa: BLE001 - validation failure must not publish source
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
    finally:
        if not result['published']:
            guarded.restore(workspace, original, root)
            events.emit('frozen_task_rolled_back', starting_version_restored=True)
        else:
            events.emit('frozen_patch_retained', correction_retained=result['correction_retained'])
        result['metrics'] = llm.metrics()
        result['final_source_hash'] = digest(snapshot(workspace))
        result['original_restored'] = result['final_source_hash'] == job['original_hash']
    return result



def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    events = Events(path.parent / 'trace.jsonl', job['policy'])
    provider = llm = None
    result = {'status': 'agent_error', 'published': False}
    started = time.monotonic()
    try:
        config = previous.repair.config()
        previous.repair.check_identity(config)
        if job['policy'] not in ('current', 'dependencies'):
            raise ValueError('Unknown evidence policy')
        provider = adapters.Provider('qwen', events)
        llm = adapters.CheckedBudgetLLM(provider, config, events)
        flow = guarded.run_candidate if job['policy'] == 'current' else expanded_candidate
        result = flow(llm, job, events)
        previous.repair.check_identity(config)
    except Exception as exc:  # noqa: BLE001 - never publish a failed comparison
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
        if (path.parent / 'original-workspace').exists():
            guarded.restore(Path(job['workspace']), path.parent / 'original-workspace', path.parent)
    finally:
        result.update(metrics=llm.metrics() if llm else None, provider_calls=provider.calls if provider else [],
                      seconds=round(time.monotonic()-started, 4))
        previous.write_json(path.parent / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
