"""Optional bounded repair with dual public validation and task-local rollback."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from docs.experiments import public_feedback_v2 as previous
from evals.runner import digest, snapshot
from evals.runtime import Events
from docs.experiments.targeted_context_v1 import retrieve


def validate(job, root):
    workspace = Path(job['workspace'])
    expected = root.resolve() / 'workspace'
    if workspace.is_symlink() or workspace.resolve() != expected:
        raise ValueError('Require owned task-local workspace')
    if digest(snapshot(workspace)) != job['original_hash']:
        raise ValueError('Original workspace changed')
    if hashlib.sha256(job['description'].encode()).hexdigest() != job['description_hash']:
        raise ValueError('Certified description changed')
    for name in ('harness', 'frozen_harness'):
        if digest(snapshot(Path(job[name]))) != job[name + '_hash']:
            raise ValueError('Certified public harness changed')
    previous.repair.validate_evidence(workspace, job['allowed_files'], job['evidence'])


def restore(workspace, source, root):
    # Only replace the explicitly owned directory, never a user's source checkout.
    if workspace.is_symlink() or workspace.resolve() != root.resolve() / 'workspace':
        raise ValueError('Rollback target is not the owned workspace')
    shutil.rmtree(workspace)
    shutil.copytree(source, workspace)


def checked(workspace, job, root, stage):
    result = {}
    for label, name in [('public', 'harness'), ('frozen', 'frozen_harness')]:
        harness = Path(job[name])
        if digest(snapshot(harness)) != job[name + '_hash']:
            raise ValueError('Certified public harness changed')
        result[label] = previous.public_check(workspace, harness, job['package'], job['source_root'],
                                               root / (stage + '-' + label))
    return result


def valid(outcomes):
    return set(outcomes) == {'public', 'frozen'} and all(previous.all_pass(v) for v in outcomes.values())


def executable(outcomes):
    return all(not group['timed_out'] and group.get('tests_run', 0) > 0
               and not any(group.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes'))
               for groups in outcomes.values() for group in groups.values())


def feedback(outcomes, workspace, job, root):
    observations = []
    for label, name in [('public', 'harness'), ('frozen', 'frozen_harness')]:
        observations.append(label + ':\n' + previous.diagnostic(outcomes[label], root / ('initial-' + label),
                                                                 workspace, Path(job[name])))
    # Keep the original readable tests in the prompt; generated guard plumbing stays out.
    return {'provenance': 'certified public checks plus fixed original observations; no private grading',
            'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
            'observations': '\n'.join(observations)[:4400]}


def initial_observation(outcomes, workspace, job, root):
    public = outcomes['public']
    if (not executable(outcomes) or public['Reproduce']['passed']
            or not public['Preserve']['passed']):
        raise ValueError('Initial public reproduction or preservation precondition failed')
    return {'provenance': 'actual original-source public reproduction; no private grading',
            'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
            'observations': previous.diagnostic(public, root / 'before-public', workspace, Path(job['harness'])),
            'source_version': 'original workspace, before any model edits'}


def run_candidate(llm, job, events):
    root = events.path.parent
    validate(job, root)
    workspace = Path(job['workspace'])
    original, initial = root / 'original-workspace', root / 'initial-workspace'
    shutil.copytree(workspace, original)
    result = {'status': 'agent_error', 'feedback_attempts': 0, 'published': False,
              'correction_retained': False, 'protocol': 'reproduction-first-v1'}
    try:
        before_checks = checked(workspace, job, root, 'before')
        result['before_checks'] = before_checks
        observation = initial_observation(before_checks, workspace, job, root)
        previous.write_json(root / 'initial-observation.json', observation)
        events.emit('initial_public_reproduction', reproduced=True, source='certified public checks')
        first = previous.request(llm, workspace, job, job['evidence'], root, 'initial', observation)
        result['initial'] = first
        result['initial_metrics'] = dict(llm.metrics())
        shutil.copytree(workspace, initial)
        if first['status'] != 'completed':
            result.update(status=first['status'], feedback_skipped='initial_not_completed')
        else:
            outcomes = checked(workspace, job, root, 'initial')
            result['initial_checks'] = outcomes
            selected = outcomes
            if not valid(outcomes) and executable(outcomes):
                evidence = retrieve(workspace, job['allowed_files'], job['description'])['evidence']
                observation = feedback(outcomes, workspace, job, root)
                result['feedback_attempts'] = 1
                second = previous.request(llm, workspace, job, evidence, root, 'feedback', observation)
                result['correction'] = second
                if second['status'] == 'completed':
                    corrected = checked(workspace, job, root, 'corrected')
                    result['correction_checks'] = corrected
                    result['correction_retained'] = valid(corrected)
                    if result['correction_retained']:
                        selected = corrected
                if not result['correction_retained']:
                    restore(workspace, initial, root)
                    events.emit('frozen_correction_rejected', initial_restored=True)
            else:
                result['feedback_skipped'] = 'checks_passed' if valid(outcomes) else 'public_execution_failure'
            result['final_checks'] = selected
            # Recheck immutable guards after generation, including the keep-initial path.
            for name in ('harness', 'frozen_harness'):
                if digest(snapshot(Path(job[name]))) != job[name + '_hash']:
                    raise ValueError('Certified public harness changed')
            result['published'] = valid(selected)
            result['status'] = 'completed' if result['published'] else 'failed_public_validation'
    except Exception as exc:  # noqa: BLE001 - validation failure must not publish source
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
    finally:
        if not result['published']:
            restore(workspace, original, root)
            events.emit('frozen_task_rolled_back', starting_version_restored=True)
        else:
            events.emit('frozen_patch_retained', correction_retained=result['correction_retained'])
        result['metrics'] = llm.metrics()
        result['final_source_hash'] = digest(snapshot(workspace))
        result['original_restored'] = result['final_source_hash'] == job['original_hash']
    return result

