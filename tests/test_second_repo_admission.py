import json

import pytest

from docs.experiments import second_repo_admission_v1 as admission


def test_candidate_pool_and_source_package_bootstrap():
    cases, identity = admission.frozen_inputs()
    assert tuple(c['case_id'] for c in cases) == admission.IDS
    assert all(c['repo'] == 'pallets/itsdangerous' for c in cases)
    assert identity['engine_hash'] == admission.ENGINE
    assert 'import itsdangerous' in admission.BOOT
    assert 'import click' not in admission.BOOT
    assert 'Submodule shadowed source' in admission.BOOT


@pytest.mark.parametrize('field,value', [('repo', 'other/repo'), ('package', 'click'),
                                        ('before_commit', 'short'), ('changed_source_files', ['../escape.py'])])
def test_invalid_candidate_rejected(tmp_path, field, value):
    data = json.loads(admission.CATALOG.read_text())
    data['cases'][0][field] = value
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Invalid candidate'):
        admission.frozen_inputs(catalog)


def test_parent_and_scope_checked_before_archive_download(tmp_path, monkeypatch):
    case = json.loads(admission.CATALOG.read_text())['cases'][0]
    calls = []
    metadata = {'sha': case['after_commit'], 'parents': [{'sha': '0' * 40}], 'files': []}

    def fetch(url):
        calls.append(url)
        return json.dumps(metadata).encode()

    monkeypatch.setattr(admission, 'fetch', fetch)
    with pytest.raises(ValueError, match='direct child'):
        admission.admit(case, tmp_path, admission.CHECKS, tmp_path / 'python')
    assert len(calls) == 1
    other = tmp_path / 'other'
    other.mkdir()
    metadata['parents'][0]['sha'] = case['before_commit']
    with pytest.raises(ValueError, match='source scope'):
        admission.admit(case, other, admission.CHECKS, tmp_path / 'python')
    assert len(calls) == 2


def test_public_projection_has_no_reference_or_scoring_fields(tmp_path):
    cases, _ = admission.frozen_inputs()
    rows = []
    for case in cases:
        source = tmp_path / case['case_id'] / 'before' / 'src/itsdangerous'
        source.mkdir(parents=True)
        (source / 'extra.py').write_text('value = 1')
        (source / 'signer.py').write_text('value = 2')
        rows.append(dict(case, admitted=True))
    tasks = admission.public_tasks(cases, {'cases': rows}, tmp_path)['tasks']
    assert len(tasks) == 3
    for task, case in zip(tasks, cases):
        assert set(task) == {'task_id', 'repo', 'before_commit', 'description', 'allowed_files'}
        assert task['description'] == case['public_problem']
        assert task['allowed_files'] == ['src/itsdangerous/extra.py', 'src/itsdangerous/signer.py']


def test_batch_preserves_network_exclusions_without_replacement(tmp_path, monkeypatch):
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
    assert attempted == list(admission.IDS)
    assert 'network failure' in report['cases'][1]['exclusion_reason']
    assert report['repair_llm_calls'] == report['embedding_calls'] == 0
    public = json.loads((tmp_path / 'output/public-tasks.json').read_text())
    assert [t['task_id'] for t in public['tasks']] == [admission.IDS[0], admission.IDS[2]]


def test_existing_output_preserved(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'keep'
    marker.write_text('keep')
    with pytest.raises(ValueError, match='fresh output'):
        admission.run(output, tmp_path / 'python')
    assert marker.read_text() == 'keep'


def test_frozen_manifest_pins_inputs_and_records_partial_diagnostic():
    base = admission.CATALOG.parent
    manifest = json.loads((base / 'second-repo-suite-v1.json').read_text())
    assert manifest['catalog_sha256'] == admission.sha(admission.CATALOG)
    assert manifest['checks_sha256'] == admission.digest(admission.snapshot(admission.CHECKS))
    assert manifest['adapter_sha256'] == admission.sha(admission.Path(admission.__file__))
    assert manifest['public_tasks_sha256'] == admission.sha(base / manifest['public_tasks'])
    assert manifest['unique_tasks'] == 3
    partial = manifest['cases'][0]['partial_results']
    assert partial[0] == {'applied_files': ['src/itsdangerous/serializer.py'], 'target_passed': False, 'controls_passed': True}
    assert partial[1] == {'applied_files': ['src/itsdangerous/signer.py'], 'target_passed': True, 'controls_passed': True}


def test_frozen_public_projection_allows_entire_package_without_fix_labels():
    base = admission.CATALOG.parent
    cases, _ = admission.frozen_inputs()
    tasks = json.loads((base / 'second-repo-public-tasks-v1.json').read_text())['tasks']
    assert len(tasks) == len(cases)
    for task, case in zip(tasks, cases):
        assert set(task) == {'task_id', 'repo', 'before_commit', 'description', 'allowed_files'}
        assert task['description'] == case['public_problem']
        assert len(task['allowed_files']) > len(case['changed_source_files'])
        assert all(p.startswith('src/itsdangerous/') and p.endswith('.py') for p in task['allowed_files'])
