"""Frozen public development checks and at most one symbol-patch feedback call."""

import hashlib
import shutil
from pathlib import Path

from .real_admission import execute
from .runner import digest, snapshot
from .symbol_patch import public_requirements, run_symbol_patch

PROTOCOL = 'symbol-feedback-development-v1'


def public_contract(description):
    requirements = public_requirements(description)
    terms = ('False-like values', 'true-like values', 'only whitespace', 'explicit command-line', 'normal argument conversion')
    if not all(any(term in row['text'] for row in requirements) for term in terms):
        raise ValueError('Public Click checks require the supported public envvar contract')
    code = Path(__file__).with_name('public_click_contract.py').read_bytes()
    return code, requirements


def check_public(workspace, harness, config, events, python, stage, frozen_hash):
    root = events.path.parent
    copy = root / ('symbol-public-' + stage)
    shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns('__pycache__'))
    before, checks_before = digest(snapshot(copy)), digest(snapshot(harness))
    if checks_before != frozen_hash:
        raise ValueError('Frozen public harness changed')
    logs = root / ('symbol-public-' + stage + '-logs')
    outcome = execute(copy, harness, 'PublicContract', logs, python, config.test_timeout)
    if digest(snapshot(copy)) != before or digest(snapshot(harness)) != checks_before:
        raise ValueError('Public checks mutated candidate or frozen harness')
    output = (logs / outcome['stderr']).read_text(encoding='utf-8', errors='replace')
    output = output.replace(str(copy), '<PUBLIC_WORKSPACE>').replace(str(harness), '<PUBLIC_CHECKS>')[-6000:]
    events.emit('symbol_public_checked', stage=stage, **outcome)
    return outcome, output


def run_symbol_feedback(llm, workspace, description, allowed_files, config, events, python):
    code, requirements = public_contract(description)
    harness = events.path.parent / 'symbol-public-harness'
    harness.mkdir()
    (harness / 'test_admission.py').write_bytes(code)
    frozen_hash = digest(snapshot(harness))
    checks = {'code_hash': hashlib.sha256(code).hexdigest(), 'requirements': requirements,
              'provenance': 'hand-authored public development checks', 'semantic_correctness_verified': False}
    events.emit('symbol_public_frozen', **checks)
    checks['original'], _ = check_public(workspace, harness, config, events, python, 'original', frozen_hash)
    first = run_symbol_patch(llm, workspace, description, allowed_files, config, events,
                              response_name='symbol-initial-response.txt')
    stages = [first]
    result = {**first, 'protocol': PROTOCOL, 'public_checks': checks, 'feedback_attempts': 0, 'patch_stages': stages,
              'initial_evidence_hash': first.get('evidence_hash'), 'initial_prompt_hash': first.get('prompt_hash')}
    if first['status'] == 'completed':
        checks['candidate'], output = check_public(workspace, harness, config, events, python, 'candidate', frozen_hash)
        valid_failure = lambda outcome: (outcome['assertion_failure'] and not outcome['execution_error']
                                         and not outcome['timed_out'] and outcome['tests_run'] > 0)
        if valid_failure(checks['original']) and valid_failure(checks['candidate']):
            events.emit('symbol_feedback_requested', code_hash=checks['code_hash'], max_attempts=1)
            final = run_symbol_patch(llm, workspace, description, allowed_files, config, events,
                                      feedback={'frozen_test_code': code.decode(), 'output': output,
                                                'source': 'public-development-checks-only'},
                                      response_name='symbol-feedback-response.txt')
            stages.append(final)
            result.update(final)
            result['feedback_attempts'] = 1
            if final['status'] == 'completed':
                checks['final'], _ = check_public(workspace, harness, config, events, python, 'final', frozen_hash)
    result['protocol'] = PROTOCOL
    result['edited_files'] = sorted({name for stage in stages for name in stage.get('edited_files', [])})
    return result
