import pytest

from docs.experiments import remaining_failure_audit_v1 as audit


def read(path):
    return path.read_text(encoding='utf-8')


def test_frames_use_candidate_snapshot_after_runtime_rollback(tmp_path):
    runtime = tmp_path / 'workspace'
    candidate = tmp_path / 'feedback-staging'
    runtime.mkdir()
    candidate.mkdir()
    (runtime / 'bug.py').write_text('original = True\n', encoding='utf-8')
    (candidate / 'bug.py').write_text('def fail():\n    missing()\n', encoding='utf-8')
    log = f'File "{runtime / "bug.py"}", line 2, in fail\nFile "{tmp_path / "test.py"}", line 8, in callback'
    frames = audit.frame_facts(log, runtime, candidate, read)
    assert len(frames) == 1
    assert frames[0]['statement'] == 'missing()'
    assert frames[0]['candidate_sha256'] == audit.sha(candidate / 'bug.py')


def test_assertion_only_does_not_invent_source_location(tmp_path):
    log = f'File "{tmp_path / "test_admission.py"}", line 9, in test\nAssertionError: 0 != 1'
    assert audit.frame_facts(log, tmp_path / 'workspace', tmp_path / 'candidate', read) == []


@pytest.mark.parametrize('line', [0, 3])
def test_stale_traceback_coordinates_rejected(tmp_path, line):
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    (candidate / 'bug.py').write_text('pass\n', encoding='utf-8')
    log = f'File "{tmp_path / "workspace" / "bug.py"}", line {line}, in fail'
    with pytest.raises(ValueError, match='outside candidate'):
        audit.frame_facts(log, tmp_path / 'workspace', candidate, read)


def test_frames_outside_runtime_are_excluded(tmp_path):
    log = f'File "{tmp_path / "workspace-other" / "bug.py"}", line 1, in fail'
    assert audit.frame_facts(log, tmp_path / 'workspace', tmp_path / 'candidate', read) == []


def test_deletion_is_zero_width_not_changed_next_line():
    changes = audit.changed_ranges('one\ntwo\nthree\n', 'one\nthree\n')
    assert changes == [{'kind': 'delete', 'before': [2, 2], 'candidate': [2, 1]}]


def test_changed_symbols_include_nested_owner():
    source = 'def outer():\n    def inner():\n        return 2\n    return inner()\n'
    ranges = audit.changed_ranges(source.replace('return 2', 'return 1'), source)
    assert {s['name'] for s in audit.edited_symbols(source, ranges)} == {'outer', 'inner'}


@pytest.mark.parametrize(('initial', 'correction', 'target', 'preserve', 'expected'), [
    ('invalid_patch', None, False, True, 'initial_invalid_patch'),
    ('output_truncated', None, False, True, 'initial_output_truncated'),
    ('completed', 'invalid_patch', False, True, 'correction_invalid_patch'),
    ('completed', 'output_truncated', False, True, 'correction_output_truncated'),
    ('completed', 'completed', True, False, 'target_pass_preserve_fail'),
    ('completed', 'completed', False, False, 'target_and_preserve_fail'),
    ('completed', 'completed', False, True, 'target_fail_preserve_pass'),
])
def test_signature_keeps_stage_failure_and_regression_distinct(initial, correction, target, preserve, expected):
    worker = {'initial': {'status': initial}, 'correction_checks': {'public': {
        'Reproduce': {'passed': target}, 'Preserve': {'passed': preserve}}}}
    if correction:
        worker['correction'] = {'status': correction}
    assert audit.signature(worker) == expected

