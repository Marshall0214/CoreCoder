import json

import pytest

from evals.runner import DEFAULT_SUITE, digest, reference_edits, run_task, snapshot
from evals.schema import RunConfig, load_suite

SUITE = DEFAULT_SUITE / 'contract-clarity-v2'


def test_versioned_task_keeps_original_frozen():
    original = DEFAULT_SUITE / 'localization-v1/artifact-routing'
    assert digest(snapshot(original)) == 'df3bdd537e6ef4d387c1f8cbcd2ead2d33239b125238da5bfe2e004b2a0c1c81'
    task = load_suite(SUITE)[0]
    assert task.task_id == 'artifact-routing-v2'
    assert json.loads((task.root / 'task.json').read_text(encoding='utf-8'))['version'] == 2
    assert reference_edits(task) == reference_edits(load_suite(DEFAULT_SUITE / 'localization-v1', ['artifact-routing'])[0])


@pytest.mark.parametrize('mode,accepted', [('unchanged', False), ('reference', True), ('scripted', True)])
def test_clarified_task_admission(tmp_path, mode, accepted):
    result = run_task(load_suite(SUITE)[0], RunConfig(mode=mode), tmp_path)
    assert result['accepted'] is accepted
    assert result['verification']['regression']['passed']
    if accepted:
        assert result['verification']['target']['passed']
