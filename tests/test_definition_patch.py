import json
import shutil

import pytest

from docs.experiments import definition_patch_v1 as adapter
from evals.staged_repair import object_hash
from tests.test_staged_replay import setup_checkpoint


def fixture(tmp_path, monkeypatch):
    source, _config, checkpoint = setup_checkpoint(tmp_path)
    monkeypatch.setattr(adapter, 'ROOT', tmp_path)
    monkeypatch.setattr(adapter, 'DATA', tmp_path)
    monkeypatch.setattr(adapter, 'check_code', lambda protocol: None)
    admitted = tmp_path / 'admitted'
    shutil.copytree(source, admitted / 'before')
    case = ({'public_problem': 'envvar'}, {}, tmp_path / 'checks', admitted, {})
    monkeypatch.setattr(adapter, 'admitted_case', lambda *args: case)
    protocol = {'purpose': 'definition-patch-development-v1', 'benchmark_eligible': False,
                'order': ['baseline', 'definition'], 'expected_patch_runs': 2, 'expected_new_localizations': 0,
                'input_files': {}, 'admission': 'admission.json', 'catalog': 'catalog.json', 'task_id': 'synthetic',
                'checkpoints': {}}
    for arm in protocol['order']:
        path = tmp_path / f'{arm}.json'
        path.write_text(json.dumps(checkpoint), encoding='utf-8')
        protocol['checkpoints'][arm] = {'path': path.name, 'sha256': adapter.file_hash(path),
                                     'checkpoint_hash': checkpoint['checkpoint_hash'],
                                     'candidate_pool_hash': checkpoint['localization_result']['candidate_pool_hash'],
                                     'localization_tokens': checkpoint['metrics']['budget_accounted_tokens']}
    return protocol, checkpoint


def test_load_pair_preserves_cost_and_read_first_inputs(tmp_path, monkeypatch):
    protocol, checkpoint = fixture(tmp_path, monkeypatch)
    _, config, pair = adapter.load_inputs(protocol)
    assert config.token_budget == 10000
    assert pair['baseline'] == pair['definition'] == checkpoint
    assert sum(c['metrics']['budget_accounted_tokens'] for c in pair.values()) == 480


def test_checkpoint_byte_drift_rejected(tmp_path, monkeypatch):
    protocol, _ = fixture(tmp_path, monkeypatch)
    (tmp_path / 'definition.json').write_text('{}')
    with pytest.raises(ValueError, match='Frozen checkpoint'):
        adapter.load_inputs(protocol)


def test_pair_config_change_rejected_even_with_valid_checkpoint(tmp_path, monkeypatch):
    protocol, checkpoint = fixture(tmp_path, monkeypatch)
    checkpoint['config']['max_output_tokens'] = 1234
    checkpoint['checkpoint_hash'] = object_hash({k: v for k, v in checkpoint.items() if k != 'checkpoint_hash'})
    path = tmp_path / 'definition.json'
    path.write_text(json.dumps(checkpoint))
    protocol['checkpoints']['definition'].update(sha256=adapter.file_hash(path), checkpoint_hash=checkpoint['checkpoint_hash'])
    with pytest.raises(ValueError, match='Paired inputs'):
        adapter.load_inputs(protocol)


def test_frozen_localization_cost_and_protocol_counts_rejected(tmp_path, monkeypatch):
    protocol, _ = fixture(tmp_path, monkeypatch)
    protocol['checkpoints']['definition']['localization_tokens'] += 1
    with pytest.raises(ValueError, match='Localization cost'):
        adapter.load_inputs(protocol)
    protocol['expected_new_localizations'] = 1
    with pytest.raises(ValueError, match='Unexpected'):
        adapter.load_inputs(protocol)
