import json

import pytest

from docs.experiments import validation_admission_v1 as admission


def groups(before=False, **overrides):
    target = {'passed': not before, 'assertion_failure': before, 'execution_error': False,
              'timed_out': False, 'tests_run': 1}
    target.update(overrides)
    return {'Target': target, 'Controls': {'passed': True}}


def test_fixed_pool_is_distinct_and_checks_exist():
    cases, identity = admission.frozen_inputs()
    assert [c['case_id'] for c in cases] == [
        'click-usage-empty', 'click-echo-empty-bytes', 'click-style-color-validation']
    assert identity['engine_hash'] == admission.ENGINE
    assert len(identity['catalog_sha256']) == len(identity['checks_sha256']) == 64


def test_development_overlap_and_pr_reordering_rejected(tmp_path):
    data = json.loads(admission.CATALOG.read_text())
    path = tmp_path / 'catalog.json'
    data['cases'][0]['after_commit'] = '70c673d37eb91ba42a129be9037caf3ebed62f3e'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='overlaps'):
        admission.frozen_inputs(path)
    data = json.loads(admission.CATALOG.read_text())
    data['cases'][0]['fix_url'] = 'https://github.com/pallets/click/pull/3493'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='order changed'):
        admission.frozen_inputs(path)


@pytest.mark.parametrize('overrides', [{'execution_error': True}, {'timed_out': True},
                                      {'tests_run': 0}, {'assertion_failure': False}])
def test_environment_errors_and_empty_target_are_not_admitted(overrides):
    row = {'revisions': {'before': {'groups': groups(True, **overrides)},
                         'after': {'groups': groups()}}}
    assert not admission.eligible(row)


def test_controls_must_pass_on_both_revisions():
    row = {'revisions': {'before': {'groups': groups(True)}, 'after': {'groups': groups()}}}
    assert admission.eligible(row)
    for label in ('before', 'after'):
        row['revisions'][label]['groups']['Controls']['passed'] = False
        assert not admission.eligible(row)
        row['revisions'][label]['groups']['Controls']['passed'] = True


def test_pinned_parent_or_source_scope_mismatch_stops_before_download(tmp_path, monkeypatch):
    case = json.loads(admission.CATALOG.read_text())['cases'][0]
    checks = tmp_path / 'checks' / case['case_id']
    checks.mkdir(parents=True)
    (checks / 'test_admission.py').write_text('# checks')
    calls = []
    metadata = {'sha': case['after_commit'], 'parents': [{'sha': '0' * 40}], 'files': []}

    def fetch(url):
        calls.append(url)
        return json.dumps(metadata).encode()

    monkeypatch.setattr(admission, 'fetch', fetch)
    with pytest.raises(ValueError, match='direct child'):
        admission.admit(case, tmp_path, tmp_path / 'checks', tmp_path / 'python')
    assert len(calls) == 1
    other = tmp_path / 'other'
    other.mkdir()
    metadata['parents'][0]['sha'] = case['before_commit']
    with pytest.raises(ValueError, match='source scope'):
        admission.admit(case, other, tmp_path / 'checks', tmp_path / 'python')
    assert len(calls) == 2


def test_batch_preserves_exclusions_without_candidate_replacement(tmp_path, monkeypatch):
    cases, identities = admission.frozen_inputs()
    monkeypatch.setattr(admission, 'frozen_inputs', lambda *_: (cases, identities))

    def environment(command, cwd, timeout, stdout, stderr, env):
        stdout.write_text(json.dumps({'prefix': 'isolated', 'base_prefix': 'base',
                                     'dependency_versions': {'colorama': None, 'typing_extensions': None}}))
        return {'returncode': 0, 'timed_out': False}

    attempted = []

    def admit(case, *_):
        attempted.append(case['case_id'])
        if len(attempted) == 2:
            raise ValueError('network failure')
        return dict(case, admitted=True)

    monkeypatch.setattr(admission, 'run_process', environment)
    monkeypatch.setattr(admission, 'admit', admit)
    report = admission.run(tmp_path / 'output', tmp_path / 'python')
    assert report['complete'] and report['admitted_count'] == 2
    assert attempted == [c['case_id'] for c in cases]
    assert report['cases'][1]['admitted'] is False
    assert 'network failure' in report['cases'][1]['exclusion_reason']
    assert report['repair_llm_calls'] == report['embedding_calls'] == 0


def test_existing_output_is_not_overwritten(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'keep'
    marker.write_text('keep')
    with pytest.raises(ValueError, match='fresh output'):
        admission.run(output, tmp_path / 'python')
    assert marker.read_text() == 'keep'


def test_validation_manifest_pins_catalog_checks_and_public_projection():
    root = admission.CATALOG.parent
    manifest = json.loads((root / 'validation-suite-v1.json').read_text())
    assert manifest['catalog_sha256'] == admission.sha(root / manifest['catalog'])
    assert manifest['checks_sha256'] == admission.digest(admission.snapshot(root / manifest['checks_root']))
    assert manifest['public_tasks_sha256'] == admission.sha(root / manifest['public_tasks'])
    assert manifest['admission_adapter_sha256'] == admission.sha(admission.Path(admission.__file__))
    assert manifest['unique_validation_tasks'] == 3
    assert all(r['admitted'] for r in manifest['cases'])


def test_public_tasks_omit_fix_labels_and_allow_entire_package():
    root = admission.CATALOG.parent
    tasks = json.loads((root / 'validation-public-tasks-v1.json').read_text())['tasks']
    cases = json.loads(admission.CATALOG.read_text())['cases']
    for task, case in zip(tasks, cases):
        assert set(task) == {'task_id', 'repo', 'before_commit', 'description', 'allowed_files'}
        assert task['description'] == case['public_problem']
        assert len(task['allowed_files']) > len(case['changed_source_files'])
        assert all(p.startswith('src/click/') and p.endswith('.py') for p in task['allowed_files'])
