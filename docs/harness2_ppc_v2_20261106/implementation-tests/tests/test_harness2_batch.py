"""Fixed-denominator paired batch orchestration, without Docker or inference."""
import json
import sys
from types import ModuleType

import pytest

from integrations import harness2 as bridge
from integrations import harness2_batch as batch
from integrations import harness2_feedback as feedback


@pytest.mark.parametrize('policy,expected,failed', [('official', 'agg1', 0),
    ('public-preserve-v1', 'base1', 0), ('public-preserve-v1', 'base1', 1)])
def test_delivery_policy_runs_after_search_and_never_requires_private_scores(tmp_path, monkeypatch, policy, expected, failed):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'code.py').write_text('x = 1', encoding='utf-8')
    root = tmp_path / 'experiment'
    root.mkdir()
    public = {'instance_id': 'example', 'problem_statement': 'fix x'}
    adapter = type('Adapter', (), {})()
    adapter.rollouts = [{'label': label, 'folder': str(root / label)} for label in ('base1', 'agg1')]
    bridge.write(root / 'base1/public.json', public)
    adapter.spec = type('Spec', (), {'channels': {'proposer': None}, 'runs_root': root / 'runs'})()
    selection_path = root / 'runs/issue-cc-agg1/example/selection/agg1/selection.json'
    schedule = ModuleType('harness2.core.schedule')

    def run_domain(*args, **kwargs):
        bridge.write(selection_path, {'ok': not failed, 'chosen_label': 'agg1'})
        return {'failed': failed}

    schedule.run_domain = run_domain
    monkeypatch.setitem(sys.modules, 'harness2.core.schedule', schedule)
    monkeypatch.setattr(batch, 'load', lambda: None)
    monkeypatch.setattr(batch, 'options', lambda *args, **kwargs: {})
    monkeypatch.setattr(bridge, 'classes', lambda *args: (lambda *a: adapter, lambda *a: None))
    monkeypatch.setattr(batch, 'collect', lambda *args: {'fresh_model_calls': 0, 'tokens': 0})
    decisions = []

    def run_child(path, *, controller=False, **kwargs):
        assert selection_path.exists()  # Search/adoption happened before this controller policy.
        assert controller is False  # Never import repair/model SDK dependencies in the 3.12 controller.
        job = bridge.read(path)
        assert set(job) == {'kind', 'rollouts', 'official_label', 'public_hash', 'source_hash', 'config'}
        assert job['kind'] == 'public-selection' and 'grading' not in json.dumps(job)
        decisions.append(job)
        bridge.write(path.parent / 'result.json', {'policy': policy,
                     'chosen_label': 'base1', 'chosen_folder': str(root / 'base1')})

    monkeypatch.setattr(batch, 'run_child', run_child)
    batch.experiment({'arm': 'harness2', 'source': str(source), 'public_task': public,
                      'source_hash': 'fixed', 'public_checks': 'public', 'package': 'pkg',
                      'feedback_rounds': 20, 'source_root': '.', 'candidate_policy': policy}, root)
    result = bridge.read(root / 'result.json')
    assert result['status'] == 'agent_completed' and result['adopted_label'] == expected
    assert result['optimization_complete'] is (not failed)
    assert bool(decisions) == (policy == 'public-preserve-v1')
    assert not result['independent_grading_available']


def test_public_selection_worker_rejects_private_inputs(tmp_path):
    bridge.write(tmp_path / 'job.json', {'kind': 'public-selection', 'case': {'checks': 'private'}})
    with pytest.raises(ValueError, match='only pinned public'):
        batch.worker(tmp_path / 'job.json')


def test_src_package_configuration_is_explicit_and_cannot_escape(tmp_path):
    (tmp_path / 'test_admission.py').write_text('# checks\n', encoding='utf-8')
    config = feedback.options(tmp_path, 'click', source_root='src')
    assert config['source_root'] == 'src'
    feedback.verify_options(config)
    assert 'source_root' not in feedback.options(tmp_path, 'toolz')
    for path in ('../outside', 'C:/host', 'src\\elsewhere', ''):
        with pytest.raises(ValueError):
            feedback.options(tmp_path, 'click', source_root=path)


def test_summary_does_not_report_unfinished_rate_or_unknown_tokens_as_zero():
    report = {'tasks': {arm: {} for arm in batch.ARMS}}
    report['tasks']['no_harness']['a'] = {'status': 'graded', 'resolved': True, 'usage': {'tokens': 10}}
    report['tasks']['harness2']['a'] = {'status': 'graded', 'resolved': False, 'usage': {'tokens': None}}
    summary = batch.summarize(report)
    assert summary['no_harness']['repair_rate'] is None
    assert summary['harness2']['actual_tokens'] is None
    assert summary['pairs']['lost_successes'] == ['a']
    report['tasks'] = {arm: {str(i): {'status': 'error', 'resolved': False} for i in range(50)} for arm in batch.ARMS}
    summary = batch.summarize(report)
    assert summary['no_harness']['repair_rate'] == 0 and summary['no_harness']['errors'] == 50


def fixture(tmp_path, monkeypatch):
    rows = [{'task_id': f'case-{i:02d}', 'repo': 'local/repo', 'before': str(tmp_path / 'source'),
             'before_hash': 'fixed', 'harness': str(tmp_path / 'public'), 'package': 'pkg', 'source_root': '.',
             'description': 'Fix the public example', 'checks': 'private-not-in-model-job', 'after': 'answer-not-in-model-job'}
            for i in range(50)]
    manifest = tmp_path / 'manifest.json'
    bridge.write(manifest, {'cases': rows})
    monkeypatch.setattr(batch, 'MANIFEST', manifest)
    monkeypatch.setattr(batch, 'CODE', ())
    monkeypatch.setattr(batch, 'load', lambda: None)
    events = []

    def child(path, *args, **kwargs):
        job = bridge.read(path)
        if job['kind'] == 'identity':
            bridge.write(path.parent / 'identity.json', {'model': 'fixed'})
        else:
            events.append(('grade', job['rollouts'][0]['folder']))
            bridge.write(path.parent / 'grading.json', {'final': {'resolved': True}})

    def run_child(path, *, controller=False, **kwargs):
        job = bridge.read(path)
        if job['kind'] == 'admission':
            bridge.write(path.parent / 'result.json', {'passed': True, 'model_calls': 0})
        else:
            assert controller and 'case' not in job and 'checks' not in job and 'after' not in job
            assert 'private-not-in-model-job' not in json.dumps(job)
            events.append(('model', str(path.parent)))
            bridge.write(path.parent / 'result.json', {'status': 'agent_completed', 'final_rollout': str(path.parent),
                'usage': {'tokens': 20, 'fresh_model_calls': 1}})

    monkeypatch.setattr(bridge, 'child', child)
    monkeypatch.setattr(batch, 'run_child', run_child)
    output = tmp_path / 'batch'
    batch.initialize(output)
    return output, events


def test_both_full_fifty_task_arms_run_fresh_and_resume_does_not_repeat(tmp_path, monkeypatch):
    output, events = fixture(tmp_path, monkeypatch)
    report = batch.execute(output)
    assert report['status'] == 'completed'
    assert [kind for kind, _ in events] == ['model', 'grade'] * 100
    for arm in batch.ARMS:
        assert report['summary'][arm]['graded'] == report['summary'][arm]['resolved'] == 50
        assert report['summary'][arm]['repair_rate'] == 1
    batch.execute(output)
    assert len(events) == 200


def test_preparation_has_no_inference_and_interrupted_attempt_is_not_retried(tmp_path, monkeypatch):
    output, events = fixture(tmp_path, monkeypatch)
    report = batch.execute(output, prepare_only=True)
    assert report['status'] == 'ready' and not events
    report['tasks']['no_harness']['case-00'] = {'status': 'started'}
    bridge.write(output / 'report.json', report)
    report = batch.execute(output)
    assert report['status'] == 'completed_with_errors'
    assert report['tasks']['no_harness']['case-00']['status'] == 'interrupted'
    assert len(events) == 198
