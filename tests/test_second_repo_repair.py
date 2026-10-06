import json
import shutil
import sys

import pytest

from docs.experiments import second_repo_repair_v1 as validation


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / 'metadata'
    root.mkdir()
    admission_root = tmp_path / 'admitted'
    admission_root.mkdir()
    public, pins, admitted = [], [], []
    for name in ('one', 'two', 'three'):
        source = admission_root / name
        for label, value in (('before', 1), ('after', 2)):
            path = source / label / 'src/itsdangerous/example.py'
            path.parent.mkdir(parents=True)
            path.write_text(f'def sample():\n    return {value}\n')
            hidden = source / label / 'tests/private.py'
            hidden.parent.mkdir()
            hidden.write_text('target_secret' if label == 'before' else 'reference_secret')
        checks = root / 'checks' / name
        checks.mkdir(parents=True)
        (checks / 'test_admission.py').write_text('# scoring_secret')
        pin = {'task_id': name, 'before_commit': '1' * 40, 'after_commit': '2' * 40,
               'before_tree_hash': validation.repair.digest(validation.repair.snapshot(source / 'before')),
               'after_tree_hash': validation.repair.digest(validation.repair.snapshot(source / 'after')),
               'checks_hash': validation.repair.digest(validation.repair.snapshot(checks))}
        pins.append(pin)
        admitted.append({'case_id': name, 'admitted': True, 'before_commit': pin['before_commit'],
                         'after_commit': pin['after_commit'], 'checks_hash': pin['checks_hash']})
        public.append({'task_id': name, 'repo': 'pallets/itsdangerous', 'before_commit': pin['before_commit'],
                       'description': 'sample must return the expected value', 'allowed_files': ['src/itsdangerous/example.py']})
    public_path = root / 'public.json'
    public_path.write_text(json.dumps({'tasks': public}))
    catalog = root / 'catalog.json'
    catalog.write_text('{}')
    admission_path = admission_root / 'admission.json'
    admission_path.write_text(json.dumps({'complete': True, 'catalog_hash': validation.repair.audit.sha(catalog),
                                         'cases': admitted, 'test_environment': {'executable': sys.executable}}))
    manifest = {'public_tasks': 'public.json', 'public_tasks_sha256': validation.repair.audit.sha(public_path),
                'catalog': 'catalog.json', 'catalog_sha256': validation.repair.audit.sha(catalog),
                'checks_root': 'checks', 'checks_sha256': validation.repair.digest(validation.repair.snapshot(root / 'checks')),
                'recorded_admission_sha256': validation.repair.audit.sha(admission_path),
                'retrieval_adapter_sha256': validation.repair.audit.sha(validation.Path(validation.retrieval.__file__)),
                'repair_adapter_sha256': validation.repair.audit.sha(validation.Path(validation.repair.__file__)),
                'adapter_sha256': validation.repair.audit.sha(validation.Path(validation.admission.__file__)),
                'engine_hash': validation.repair.audit.ENGINE, 'cases': pins}
    path = root / 'manifest.json'
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(validation, 'MANIFEST_SHA', validation.repair.audit.sha(path))
    return path, admission_path, tmp_path / 'output'


def test_prepare_projects_public_inputs_without_hidden_labels(fixture):
    path, admitted, output = fixture
    cases, grading, _ = validation.prepare(path, admitted, output)
    assert len(cases) == len(grading) == 3
    assert all(set(c) == {'task_id', 'before', 'before_hash', 'description', 'allowed_files'} for c in cases)
    assert all('after_hash' in g and 'checks' in g for g in grading)
    output.mkdir()
    observed = validation.observe_all(cases, output)
    encoded = json.dumps(observed)
    assert all(secret not in encoded for secret in ('target_secret', 'reference_secret', 'scoring_secret'))
    assert all(set(r['policies']) == set(validation.repair.POLICIES) for r in observed)


@pytest.mark.parametrize('target', ['manifest', 'public', 'before', 'checks', 'admission'])
def test_changed_inputs_rejected_before_selection(fixture, target):
    manifest, admitted, output = fixture
    paths = {'manifest': manifest, 'public': manifest.parent / 'public.json', 'admission': admitted,
             'before': admitted.parent / 'one/before/src/itsdangerous/example.py',
             'checks': manifest.parent / 'checks/one/test_admission.py'}
    paths[target].write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        validation.prepare(manifest, admitted, output)
    assert not output.exists()


def test_extra_reference_fields_rejected_even_with_matching_public_hash(fixture, monkeypatch):
    manifest_path, admitted, output = fixture
    public_path = manifest_path.parent / 'public.json'
    document = json.loads(public_path.read_text())
    document['tasks'][0]['after_commit'] = '2' * 40
    public_path.write_text(json.dumps(document))
    manifest = json.loads(manifest_path.read_text())
    manifest['public_tasks_sha256'] = validation.repair.audit.sha(public_path)
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(validation, 'MANIFEST_SHA', validation.repair.audit.sha(manifest_path))
    with pytest.raises(ValueError, match='Public projection'):
        validation.prepare(manifest_path, admitted, output)


def test_existing_or_snapshot_output_rejected(fixture):
    manifest, admitted, output = fixture
    for path in (admitted.parent / 'one/before/out', output):
        if path == output:
            path.mkdir()
        with pytest.raises(ValueError, match='fresh output'):
            validation.prepare(manifest, admitted, path)


def test_all_evidence_precedes_scoring_and_six_fresh_jobs_keep_regression_failures(fixture, monkeypatch):
    manifest, admitted, output = fixture
    monkeypatch.setattr(validation.repair, 'check_identity', lambda *_: None)
    calls = []

    def groups(source, checks, *rest):
        observed = json.loads((output / 'observations.json').read_text())
        assert len(observed) == 3
        assert all(set(o['policies']) == set(validation.repair.POLICIES) for o in observed)
        before = source.name == 'before'
        return {'Target': {'passed': not before, 'assertion_failure': before, 'execution_error': False, 'timed_out': False},
                'Controls': {'passed': True}}

    def process(command, workspace, *rest):
        path = workspace.parent
        job = json.loads((path / 'job.json').read_text())
        assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
        assert 'secret' not in json.dumps(job)
        calls.append(path.name)
        metrics = {'prompt_tokens': 80, 'completion_tokens': 20, 'budget_accounted_tokens': 100, 'missing_usage_calls': 0}
        (path / 'worker-result.json').write_text(json.dumps({'status': 'completed', 'metrics': metrics}))
        return {'returncode': 0, 'timed_out': False, 'seconds': 1}

    def verify(case, source, checks, workspace, original, allowed, root, python, timeout):
        regression = root.name == validation.repair.POLICIES[1] and case['case_id'] != 'one'
        return {'passed': regression, 'target': {'passed': True}, 'regression': {'passed': regression}}

    monkeypatch.setattr(validation.admission, 'checked_groups', groups)
    monkeypatch.setattr(validation.repair, 'run_process', process)
    monkeypatch.setattr(validation, 'verify', verify)
    validation.run(manifest, admitted, output)
    report = json.loads((output / 'experiment.json').read_text())
    assert report['complete'] and len(report['runs']) == 6
    assert report['summary'][validation.repair.POLICIES[0]]['passed'] == 0
    assert report['summary'][validation.repair.POLICIES[1]]['passed'] == 2
    assert calls[:4] == [validation.repair.POLICIES[0], validation.repair.POLICIES[1],
                         validation.repair.POLICIES[1], validation.repair.POLICIES[0]]


def test_verifier_uses_clean_copy_and_requires_controls(fixture, monkeypatch):
    manifest, admitted, output = fixture
    cases, grading, _ = validation.prepare(manifest, admitted, output)
    case, item = cases[0], grading[0]
    output.mkdir()
    workspace = output / 'workspace'
    shutil.copytree(case['before'], workspace)
    original = validation.repair.snapshot(workspace)
    (workspace / case['allowed_files'][0]).write_text('def sample():\n    return 2\n')

    def groups(source, checks, *rest):
        assert source != workspace and source.name == 'grading'
        assert (source / case['allowed_files'][0]).read_text().endswith('return 2\n')
        assert checks == item['checks']
        return {'Target': {'passed': True}, 'Controls': {'passed': False}}

    monkeypatch.setattr(validation.admission, 'checked_groups', groups)
    result = validation.verify(item['case'], item['source_root'], item['checks'], workspace, original,
                               case['allowed_files'], output, item['python'])
    assert not result['passed'] and result['target']['passed']
    assert not result['regression']['passed']
    assert validation.repair.digest(validation.repair.snapshot(case['before'])) == case['before_hash']


def test_verifier_rejects_changes_outside_package_before_testing(fixture, monkeypatch):
    manifest, admitted, output = fixture
    cases, grading, _ = validation.prepare(manifest, admitted, output)
    case, item = cases[0], grading[0]
    output.mkdir()
    workspace = output / 'workspace'
    shutil.copytree(case['before'], workspace)
    original = validation.repair.snapshot(workspace)
    (workspace / 'tests/private.py').write_text('tampered')
    result = validation.verify(item['case'], item['source_root'], item['checks'], workspace, original,
                               case['allowed_files'], output, item['python'])
    assert result['scope_violations'] == ['tests/private.py']
    assert not result['passed'] and not (output / 'grading').exists()
