import hashlib
import json
from pathlib import Path

import pytest

from docs.experiments import anchored_patch_comparison_v1 as comparison
from docs.experiments import anchored_patch_v1 as anchored


def evidence(root, name='sample.py', start=1, end=None):
    data = (root / name).read_bytes()
    lines = data.decode().splitlines(keepends=True)
    end = len(lines) if end is None else end
    return {'path': name, 'start_line': start, 'end_line': end,
            'content_hash': hashlib.sha256(data).hexdigest(), 'content': ''.join(lines[start - 1:end])}


def edit(start=2, end=2, new='    return 2\n', fragment='f1'):
    return {'fragment_id': fragment, 'start_line': start, 'end_line': end, 'new': new}


def apply(root, rows, edits):
    return anchored.apply_anchored_patch(json.dumps({'edits': edits}), root, list({r['path'] for r in rows}), rows)


def test_ranges_use_original_coordinates_and_preserve_unicode_crlf(tmp_path):
    original = 'def a():\r\n    return 1\r\ndef b():\r\n    return 1\r\n# 中文\r\n'.encode()
    (tmp_path / 'sample.py').write_bytes(original)
    rows = [evidence(tmp_path)]
    fragments = anchored.fragments_for_model(rows)
    assert fragments[0]['content'].startswith('1:def a():\r\n2:    return 1\r\n')
    assert apply(tmp_path, rows, [edit(new='    x = 2\r\n    return x\r\n'), edit(4, 4, '    return 3\r\n')]) == ['sample.py']
    assert (tmp_path / 'sample.py').read_bytes() == (
        'def a():\r\n    x = 2\r\n    return x\r\ndef b():\r\n    return 3\r\n# 中文\r\n'.encode())


@pytest.mark.parametrize('bad', [edit(0, 2), edit(2, 3), edit(True, 2), edit(fragment='f9'),
                                     {**edit(), 'old': 'return 1'}, {**edit(), 'new': None}])
def test_invalid_second_edit_does_not_write_first_file(tmp_path, bad):
    for name in ('sample.py', 'other.py'):
        (tmp_path / name).write_text('def a():\n    return 1\n', encoding='utf-8')
    rows = [evidence(tmp_path), evidence(tmp_path, 'other.py')]
    original = {r['path']: (tmp_path / r['path']).read_bytes() for r in rows}
    with pytest.raises(ValueError):
        apply(tmp_path, rows, [edit(fragment='f2'), bad])
    assert {name: (tmp_path / name).read_bytes() for name in original} == original


def test_overlapping_fragments_cannot_double_edit_same_line(tmp_path):
    (tmp_path / 'sample.py').write_text('def a():\n    return 1\n', encoding='utf-8')
    rows = [evidence(tmp_path), evidence(tmp_path, start=2)]
    with pytest.raises(ValueError, match='Overlapping'):
        apply(tmp_path, rows, [edit(), edit(fragment='f2')])
    assert (tmp_path / 'sample.py').read_text().endswith('return 1\n')


def test_stale_source_and_forged_citation_rejected(tmp_path):
    (tmp_path / 'sample.py').write_text('def a():\n    return 1\n', encoding='utf-8')
    row = evidence(tmp_path)
    with pytest.raises(ValueError, match='citation'):
        apply(tmp_path, [{**row, 'content': 'fabricated'}], [edit()])
    (tmp_path / 'sample.py').write_text('def a():\n    return 3\n', encoding='utf-8')
    with pytest.raises(ValueError, match='version'):
        apply(tmp_path, [row], [edit()])
    assert (tmp_path / 'sample.py').read_text().endswith('return 3\n')


def test_scope_empty_patch_and_edit_limit(tmp_path):
    (tmp_path / 'sample.py').write_text('def a():\n    return 1\n', encoding='utf-8')
    rows = [evidence(tmp_path, start=2)]
    assert apply(tmp_path, rows, []) == []
    with pytest.raises(ValueError, match='allowed'):
        anchored.apply_anchored_patch(json.dumps({'edits': [edit()]}), tmp_path, [], rows)
    with pytest.raises(ValueError, match='Too many'):
        apply(tmp_path, rows, [edit()] * 21)
    with pytest.raises(ValueError, match='outside'):
        apply(tmp_path, rows, [edit(1, 2)])


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_missing_terminator_cannot_join_untouched_next_line(tmp_path, newline):
    (tmp_path / 'sample.py').write_bytes(f'def a():{newline}    return 1{newline}# untouched{newline}'.encode())
    rows = [evidence(tmp_path)]
    apply(tmp_path, rows, [edit(new='    return 2')])
    assert (tmp_path / 'sample.py').read_bytes() == (
        f'def a():{newline}    return 2{newline}# untouched{newline}'.encode())


def test_deletion_and_unterminated_eof(tmp_path):
    (tmp_path / 'sample.py').write_bytes(b'# remove\nvalue = 1')
    rows = [evidence(tmp_path)]
    apply(tmp_path, rows, [edit(1, 1, ''), edit(2, 2, 'value = 2')])
    assert (tmp_path / 'sample.py').read_bytes() == b'value = 2'


def result_row(policy, accepted=True, metrics=None, number=1, task='case'):
    return {'repeat': number, 'task_id': task, 'policy': policy, 'accepted': accepted,
            'status': 'passed' if accepted else 'invalid_patch', 'worker': {'metrics': metrics}, 'process': {'seconds': 1}}


def test_summary_preserves_missing_usage_and_partial_pairs():
    rows = [result_row('exact-old'), result_row('anchored-lines', False), result_row('anchored-lines', task='partial')]
    summary = comparison.summarize(rows)
    assert summary['pairs'] == {'both_passed': 0, 'exact_only': 1, 'anchored_only': 0, 'both_failed': 0, 'incomplete': 1}
    assert summary['exact-old']['budget_accounted_tokens'] is None
    assert summary['anchored-lines']['missing_metrics_runs'] == 2
    with pytest.raises(ValueError, match='duplicate'):
        comparison.summarize(rows + [rows[0]])
    with pytest.raises(ValueError, match='Unknown'):
        comparison.summarize([result_row('unknown')])


@pytest.mark.parametrize('repeats', [0, 4, True])
def test_repeat_bounds_before_any_side_effect(tmp_path, repeats):
    with pytest.raises(ValueError, match='Repeat'):
        comparison.run(tmp_path / 'unused', repeats)
    assert not (tmp_path / 'unused').exists()


def test_paired_runner_uses_same_public_evidence_and_independent_verification(tmp_path, monkeypatch):
    cases, grading = [], []
    for prefix in ('click-', 'itsdangerous-'):
        for number in range(3):
            name = f'{prefix}{number}'
            source = tmp_path / name
            for label, value in (('before', 1), ('after', 2)):
                (source / label).mkdir(parents=True)
                (source / label / 'sample.py').write_text(f'def sample():\n    return {value}\n', encoding='utf-8')
            checks = source / 'checks'
            checks.mkdir()
            (checks / 'private.py').write_text('SCORING_SECRET', encoding='utf-8')
            cases.append({'task_id': name, 'before': source / 'before', 'before_hash': comparison.repair.digest(
                comparison.repair.snapshot(source / 'before')), 'description': 'sample returns the expected value',
                'allowed_files': ['sample.py']})
            grading.append({'case': {'checks_hash': comparison.repair.digest(comparison.repair.snapshot(checks))},
                                'checks': checks, 'source_root': source, 'python': Path('unused'),
                                'after_hash': comparison.repair.digest(comparison.repair.snapshot(source / 'after'))})
    monkeypatch.setattr(comparison, 'prepare', lambda output: (cases, grading))
    monkeypatch.setattr(comparison.repair, 'check_identity', lambda config: None)
    output = tmp_path / 'output'

    def groups(workspace, *args):
        assert len(json.loads((output / 'observations.json').read_text())) == 6
        passed = workspace.name == 'after'
        return {'Target': {'passed': passed, 'assertion_failure': not passed, 'execution_error': False, 'timed_out': False},
                'Controls': {'passed': True}}

    monkeypatch.setattr(comparison.repair, 'checked_groups', groups)
    monkeypatch.setattr(comparison.second.admission, 'checked_groups', groups)
    jobs = {}

    def process(command, workspace, timeout, stdout, stderr, env):
        job_path = Path(command[-1])
        job = json.loads(job_path.read_text())
        assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
        assert 'SCORING_SECRET' not in json.dumps(job)
        key = job_path.parent.parent.name
        jobs.setdefault(key, []).append(job['evidence'])
        assert (workspace / 'sample.py').read_text().endswith('return 1\n')
        (workspace / 'sample.py').write_text('def sample():\n    return 2\n', encoding='utf-8')
        (job_path.parent / 'worker-result.json').write_text(json.dumps({'status': 'completed', 'metrics': None}))
        return {'returncode': 0, 'timed_out': False, 'seconds': 1}

    def verify(case, source, checks, workspace, original, allowed, root, python, timeout):
        assert (checks / 'private.py').read_text() == 'SCORING_SECRET'
        # One regression fails despite completed patches; never equate generation with accepted repair.
        return {'passed': not (source.name == 'click-0' and root.name == 'anchored-lines')}

    monkeypatch.setattr(comparison, 'run_process', process)
    monkeypatch.setattr(comparison.repair, 'verify', verify)
    monkeypatch.setattr(comparison.second, 'verify', verify)
    comparison.run(output)
    report = json.loads((output / 'experiment.json').read_text())
    assert report['complete'] and len(report['runs']) == 12
    assert all(len(values) == 2 and values[0] == values[1] for values in jobs.values())
    assert report['summary']['pairs']['exact_only'] == 1
    assert report['summary']['pairs']['both_passed'] == 5
    assert report['protocol']['benchmark_eligible'] is False
    with pytest.raises(ValueError, match='fresh'):
        # Restore real prepare's earliest output guard without reading local admissions.
        monkeypatch.undo()
        comparison.prepare(output)
