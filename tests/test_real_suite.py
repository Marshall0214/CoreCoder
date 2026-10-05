import json
from pathlib import Path

import pytest

from evals.real_admission import DATA
from evals.real_suite import load_manifest, prepare, run_suite


def test_frozen_manifest_covers_all_seven_tasks():
    data, entries = load_manifest(DATA / 'development-suite-v1.json')
    assert len(entries) == len({entry[2] for entry in entries}) == 7
    assert data['config']['search_backend'] == 'off'
    assert data['repeat'] == 3


@pytest.mark.parametrize('mutation', ['catalog', 'order', 'config', 'split'])
def test_manifest_rejects_drift(tmp_path, mutation):
    path = DATA / 'development-suite-v1.json'
    data = json.loads(path.read_text())
    for source in data['sources']:
        target = tmp_path / source['catalog']
        target.write_bytes((DATA / source['catalog']).read_bytes())
    if mutation == 'catalog':
        (tmp_path / data['sources'][0]['catalog']).write_text('{}')
    elif mutation == 'order':
        data['sources'][0]['tasks'].reverse()
    elif mutation == 'config':
        del data['config']['token_budget']
    else:
        data['split'] = 'held-out'
    manifest = tmp_path / 'suite.json'
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_manifest(manifest)


def test_prepare_rejects_mixed_environments(monkeypatch):
    monkeypatch.setattr('evals.real_suite.admitted_case',
                        lambda admission, catalog, task: (task, {'executable': str(admission)}))
    with pytest.raises(ValueError, match='same recorded test environment'):
        prepare([('one', Path('catalog'), 'a'), ('two', Path('catalog'), 'b')],
                {'one': Path('env-a'), 'two': Path('env-b')})


@pytest.mark.parametrize('cancel', [False, True])
def test_batch_preserves_failures_repetitions_and_incomplete_matrix(tmp_path, monkeypatch, cancel):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}')
    admission = tmp_path / 'admission.json'
    admission.write_text('{}')
    from evals.schema import RunConfig

    data = {'suite_id': 'test', 'repeat': 2, 'config': RunConfig(mode='live').to_dict()}
    monkeypatch.setattr('evals.real_suite.load_manifest', lambda path: (data, [('one', Path('catalog'), 'a')]))
    protected = tmp_path / 'protected'
    monkeypatch.setattr('evals.real_suite.prepare', lambda entries, admissions:
                        [('a', None, protected / 'checks', protected / 'source', {})])
    seen = []

    def run(*args):
        config = args[-2]
        seen.append(config.to_dict())
        return {'task_id': 'a', 'status': 'cancelled' if cancel else 'failed_verification', 'accepted': False}

    monkeypatch.setattr('evals.real_suite.run_real', run)
    monkeypatch.setattr('evals.real_suite.write_summary', lambda reports, output: None)
    output = tmp_path / 'runs'
    report = run_suite(manifest, {'one': admission}, output, 'live')
    saved = json.loads((output / 'suite-report.json').read_text())
    assert saved['expected_runs'] == 2
    assert saved['completed_runs'] == (1 if cancel else 2)
    assert saved['complete'] is (not cancel)
    assert [row['repetition'] for row in report['runs']] == ([1] if cancel else [1, 2])
    assert all(config == data['config'] for config in seen)
    assert not saved['benchmark_eligible']
