import hashlib
import json
from pathlib import Path

import pytest

from docs.experiments import salt_relations_feedback_v1 as comparison
from docs.experiments import salt_relations_worker_v1 as worker
from evals.runtime import BudgetExceeded
from tests.test_repair_public_feedback import FakeLLM, setup  # noqa: F401 - shared pytest fixture


@pytest.fixture
def salt_setup(setup):  # noqa: F811 - pytest fixture injection
    job, events, initial, final, calls = setup
    job['task_id'] = worker.relations.TASK
    code = worker.relations.CHECK
    (Path(job['harness']) / 'test_admission.py').write_bytes(code.read_bytes())
    job['harness_hash'] = worker.repair.digest(worker.repair.snapshot(Path(job['harness'])))
    job['check_code_hash'] = worker.repair.audit.sha(code)
    job['relations'] = json.loads((worker.relations.ROOT / 'docs/salt-relations-audit-v1.json').read_text(encoding='utf-8'))['contract']['rules']
    job['relations_hash'] = hashlib.sha256(json.dumps(job['relations'], sort_keys=True).encode()).hexdigest()
    return job, events, initial, final, calls


@pytest.mark.parametrize('policy', worker.POLICIES)
def test_matrix_only_in_selected_feedback_and_one_retry(salt_setup, policy):
    job, events, initial, final, calls = salt_setup
    job['policy'] = policy
    llm = FakeLLM([initial, final])
    result = worker.run_candidate(llm, job, events)
    assert result['public_checks']['final']['passed'] and result['feedback_attempts'] == 1
    assert len(llm.messages) == 2 and calls == ['public-original', 'public-candidate', 'public-final']
    first, second = [json.loads(m[1]['content']) for m in llm.messages]
    assert set(first) == {'description', 'allowed_files', 'fragments'}
    feedback = second['public_check_feedback']
    assert ('public_parameter_relations' in feedback) == (policy == worker.POLICIES[1])
    assert 'positive' not in feedback and 'historical_candidates' not in feedback


def test_only_intervention_is_feedback_relation_field(salt_setup):
    job, events, initial, final, _ = salt_setup
    messages = []
    for policy in worker.POLICIES:
        row = job['evidence'][0]
        (Path(job['workspace']) / row['path']).write_bytes(row['content'].encode('utf-8'))
        job['policy'] = policy
        llm = FakeLLM([initial, final])
        worker.run_candidate(llm, job, events)
        messages.append(llm.messages)
    assert messages[0][0] == messages[1][0]
    left, right = [json.loads(m[1][1]['content']) for m in messages]
    assert right['public_check_feedback'].pop('public_parameter_relations') == job['relations']
    assert left == right and messages[0][1][0] == messages[1][1][0]


def test_changed_matrix_rejected_before_model(salt_setup):
    job, events, initial, _, _ = salt_setup
    job['policy'] = worker.POLICIES[1]
    job['relations'][0]['effective'] = 'changed'
    llm = FakeLLM([initial])
    with pytest.raises(ValueError, match='matrix changed'):
        worker.run_candidate(llm, job, events)
    assert not llm.messages


def test_feedback_budget_stop_preserves_first_stage(salt_setup):
    job, events, initial, _, _ = salt_setup
    job['policy'] = worker.POLICIES[1]
    progress = {}
    with pytest.raises(BudgetExceeded):
        worker.run_candidate(FakeLLM([initial, BudgetExceeded('stop')]), job, events, progress)
    assert progress['initial']['status'] == 'completed'
    assert progress['feedback_attempts'] == 1 and len(progress['stages']) == 1


@pytest.mark.parametrize('repeats', [0, 4, True])
def test_invalid_repeats_rejected_before_inputs(tmp_path, repeats):
    with pytest.raises(ValueError, match='Repeat'):
        comparison.run(tmp_path / 'unused', repeats)
