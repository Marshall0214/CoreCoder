import json

import pytest

from docs.experiments import validation_repeat_v2 as runner
from tests import test_validation_repair as fixtures


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    return fixtures.fixture.__wrapped__(tmp_path, monkeypatch)


def setup(fixture, monkeypatch):
    manifest, admitted, output = fixture
    monkeypatch.setattr(runner.validation, 'MANIFEST', manifest)
    monkeypatch.setattr(runner, 'MANIFEST_SHA', runner.validation.MANIFEST_SHA)
    cases, _, _ = runner.prepare(manifest, admitted, output)
    evidence = output.parent / 'evidence'
    evidence.mkdir()
    runner.observe_all(cases, evidence)
    corrected = manifest.parent / 'corrected'
    corrected.mkdir()
    (corrected / 'test_admission.py').write_text('# corrected checks')
    spec = manifest.parent / 'prospective.json'
    spec.write_text(json.dumps({'v1_manifest_sha256': runner.MANIFEST_SHA,
                               'config': runner.repair.config().to_dict(),
                               'observations_sha256': runner.repair.audit.sha(evidence / 'observations.json'),
                               'corrected_task': 'one', 'updated_checks': 'corrected',
                               'updated_checks_sha256': runner.repair.digest(runner.repair.snapshot(corrected))}))
    monkeypatch.setattr(runner, 'SPEC', spec)
    monkeypatch.setattr(runner, 'SPEC_SHA', runner.repair.audit.sha(spec))
    monkeypatch.setattr(runner.repair, 'check_identity', lambda *_: None)
    return admitted, output, corrected


def test_frozen_scoring_rejected_before_calls(fixture, monkeypatch):
    admitted, output, corrected = setup(fixture, monkeypatch)
    (corrected / 'test_admission.py').write_text('changed')
    with pytest.raises(ValueError, match='Corrected checks changed'):
        runner.run(admitted, output)
    assert not output.exists()


@pytest.mark.parametrize('interrupt', [False, True])
def test_repeat_new_workspaces_order_scoring_and_partial_results(fixture, monkeypatch, interrupt):
    admitted, output, corrected = setup(fixture, monkeypatch)
    calls = []

    def groups(source, checks, *rest):
        assert len(json.loads((output / 'observations.json').read_text())) == 3
        if source.parent.name == 'one':
            assert checks == corrected
        before = source.name == 'before'
        return {'Target': {'passed': not before, 'assertion_failure': before,
                           'execution_error': False, 'timed_out': False}, 'Controls': {'passed': True}}

    def process(command, workspace, *rest):
        if interrupt and len(calls) == 7:
            raise RuntimeError('interrupted worker')
        job = json.loads((workspace.parent / 'job.json').read_text())
        assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
        assert 'secret' not in json.dumps(job)
        assert workspace not in calls
        calls.append(workspace)
        (workspace.parent / 'worker-result.json').write_text(json.dumps(
            {'status': 'completed', 'prompt_hash': workspace.parent.name, 'metrics':
             {'prompt_tokens': 80, 'completion_tokens': 20, 'budget_accounted_tokens': 100, 'missing_usage_calls': 0}}))
        return {'returncode': 0, 'timed_out': False, 'seconds': 1}

    def verify(case, source, checks, workspace, original, allowed, root, python, timeout):
        assert checks == corrected if case['case_id'] == 'one' else checks != corrected
        return {'passed': root.name == runner.repair.POLICIES[1]}

    monkeypatch.setattr(runner.repair, 'checked_groups', groups)
    monkeypatch.setattr(runner.repair, 'run_process', process)
    monkeypatch.setattr(runner.repair, 'verify', verify)
    if interrupt:
        with pytest.raises(RuntimeError, match='interrupted worker'):
            runner.run(admitted, output)
    else:
        runner.run(admitted, output)
    report = json.loads((output / 'experiment.json').read_text())
    assert len(report['runs']) == (7 if interrupt else 18)
    assert report['complete'] is (not interrupt)
    assert report['protocol']['prior_runs_included'] is False
    assert calls[0].parent.name != calls[6].parent.name
    if not interrupt:
        assert report['paired'] == {'function_only': 9}
        assert all(g['prompt_identical'] for row in report['per_task'] for g in row['policies'].values())
