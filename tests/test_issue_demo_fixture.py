"""Fresh-checkout synthetic demo preparation, with all execution/network mocked."""
import json

import pytest

from repairflow import issue_demo_fixture as fixture
from repairflow.bundles import read
from repairflow.issue_registry import load
from sandbox import runner


@pytest.fixture
def offline(monkeypatch):
    import urllib.request

    from repairflow.github_issue import PublicGitHub
    from repairflow.issue_providers import OllamaProvider

    def refuse(*args, **kwargs):
        pytest.fail('Synthetic preparation must not access a network or model')

    monkeypatch.setattr(urllib.request, 'build_opener', refuse)
    monkeypatch.setattr(PublicGitHub, 'get', refuse)
    monkeypatch.setattr(OllamaProvider, 'chat', refuse)
    monkeypatch.setattr(runner, 'preflight', lambda image=None: {'backend': 'docker', 'image': image,
                                                              'image_id': 'sha256:' + '1' * 64})

    def run(*args):
        failed = args[5] == 'Reproduce'
        return {'tests_run': 1, 'failures': int(failed), 'errors': 0, 'skipped': 0, 'expected_failures': 0,
                'unexpected_successes': 0, 'successful': not failed, 'returncode': int(failed), 'timed_out': False}

    monkeypatch.setattr(runner, 'run', run)


def test_prepare_is_self_contained_registered_and_explicitly_synthetic(tmp_path, offline):
    root = tmp_path / 'inputs'
    entry = fixture.prepare(root)
    metadata, task = load(entry)
    assert entry == root / 'catalog/sample' and metadata['schema_version'] == 2
    assert metadata['engine'] == 'feedback-actions-v2' and metadata['scripted_responses']
    assert task['ready_for_repair'] and task['read_only_files'] == ['src/pkg/dependency.py']
    assert 'Synthetic offline fixture' in task['description']
    assert (entry / 'prepared/source/src/pkg/__init__.py').read_text(encoding='utf-8') == fixture.SOURCE
    manifest = read(root / 'fixture-manifest.json')
    assert manifest['synthetic'] and manifest['network_requests'] == manifest['fresh_model_calls'] == 0
    assert manifest['github_identity_is_placeholder'] and manifest['commit_is_placeholder']
    assert len(manifest['endpoints_satisfied_in_memory']) == 3
    assert read(entry / 'prepared/fixture-manifest.json') == manifest
    assert read(root / 'bootstrap-receipt.json')['network_requests'] == 0
    rows = [json.loads(value) for value in read(entry / 'responses.json')]
    assert [row['action'] for row in rows] == ['finish', 'read_symbol', 'apply_patch', 'read_symbol',
                                              'read_symbol', 'apply_patch']


def test_synthetic_entry_inputs_are_frozen_by_existing_registry_hashes(tmp_path, offline):
    entry = fixture.prepare(tmp_path / 'inputs')
    (entry / 'prepared/source/src/pkg/dependency.py').write_text('STEP = 99\n', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        load(entry)


def test_existing_output_is_refused_without_execution(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail('Existing output must be rejected before Docker admission')

    monkeypatch.setattr(runner, 'preflight', refuse)
    with pytest.raises(ValueError, match='fresh'):
        fixture.prepare(tmp_path)


def test_inline_client_refuses_arbitrary_endpoints_and_oversize_reads():
    client = fixture.OfflineFixtureClient()
    with pytest.raises(ValueError, match='network endpoint'):
        client.get('https://example.invalid/untrusted')
    with pytest.raises(ValueError, match='response limit'):
        client.get(next(iter(client.replies)), limit=1)
    assert not client.requests
    other = fixture.OfflineFixtureClient()
    assert client.replies == other.replies  # In-memory ZIP timestamps are fixed.


def test_failed_admission_is_preserved_without_registering_an_entry(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(runner, 'run', lambda *args: {'tests_run': 1, 'failures': 0, 'errors': 0, 'skipped': 0,
        'expected_failures': 0, 'unexpected_successes': 0, 'successful': True, 'returncode': 0, 'timed_out': False})
    root = tmp_path / 'inputs'
    with pytest.raises(ValueError, match='admission failed'):
        fixture.prepare(root)
    manifest = read(root / 'fixture-manifest.json')
    assert not manifest['ready_for_repair'] and manifest['admission_status'] == 'not_reproduced'
    assert manifest['network_requests'] == manifest['fresh_model_calls'] == 0
    assert not (root / 'catalog/sample').exists()
