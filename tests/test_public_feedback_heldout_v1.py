import json

import pytest

from docs.experiments import public_feedback_heldout_cases_v1 as examples
from docs.experiments import public_feedback_heldout_report_v1 as reporting
from docs.experiments import public_feedback_heldout_v1 as experiment
from docs.experiments import public_feedback_v2 as frozen


def row(task, strategy, accepted, controls=True):
    return {'task_id': task, 'policy': strategy, 'accepted': accepted,
            'verification': {'groups': {'Controls': {'passed': controls}}}}


def test_gate_requires_every_pair_positive_net_gain_and_no_new_control_failure():
    rows = [row(str(i), p, i > 0 or p == 'public-feedback') for i in range(20)
            for p in ('single', 'public-feedback')]
    result = experiment.paired(rows)
    assert result['gained'] == ['0'] and not result['lost']
    assert experiment.eligible(result)
    assert not experiment.eligible(experiment.paired(rows[:-2]))
    rows[-1]['verification']['groups']['Controls']['passed'] = False
    assert not experiment.eligible(experiment.paired(rows))
    with pytest.raises(ValueError, match='Duplicate'):
        experiment.paired(rows + [rows[0]])
    with pytest.raises(ValueError, match='Incomplete'):
        experiment.paired(rows[:-1])


def test_job_omits_private_grader_and_reference_paths():
    case = {'description': 'public requirement', 'allowed_files': ['module.py'], 'package': 'example',
            'source_root': '.', 'before': 'original', 'after': 'secret reference', 'checks': 'private grader'}
    job = experiment.job_for(case, 'workspace', [], {'harness': 'public tests', 'harness_hash': 'hash'})
    assert set(job) == {'description', 'allowed_files', 'package', 'source_root',
                        'workspace', 'evidence', 'harness', 'harness_hash'}
    assert 'secret reference' not in json.dumps(job) and 'private grader' not in json.dumps(job)


def test_heldout_checks_compilable_and_separate_from_development_examples():
    assert len(examples.CASES) == 20
    assert set(examples.CASES).isdisjoint(frozen.examples.CASES)
    for task in examples.CASES:
        source = examples.code(task)
        compile(source, task, 'exec')
        assert 'class Reproduce' in source and 'class Preserve' in source
        assert 'evals.' not in source and 'docs.experiments' not in source


def test_reject_output_containing_or_nested_under_frozen_input(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    cases = [{'before': str(source), 'after': str(source), 'checks': str(source)}]
    with pytest.raises(ValueError, match='overlaps'):
        experiment.fresh_output(source / 'nested', cases)
    with pytest.raises(ValueError, match='Fresh'):
        experiment.fresh_output(tmp_path, cases)


def test_development_gate_must_have_passed_before_heldout_certification(tmp_path):
    path = tmp_path / 'development.json'
    path.write_text(json.dumps({'complete': True, 'gate_passed': False, 'runs': [None] * 60}))
    with pytest.raises(ValueError, match='eligible'):
        experiment.require_development(path)


def test_known_regression_blocks_adoption_even_when_frozen_score_gate_passes():
    pairs = {'tasks': 20, 'gained': ['a', 'b'], 'lost': [], 'new_control_failures': []}
    assert experiment.eligible(pairs)
    assert reporting.decision(pairs) == 'validated_optional_policy'
    assert reporting.decision(pairs, {'known_regression': True}) == 'do_not_adopt_known_public_regression'
    assert reporting.decision(dict(pairs, gained=[])) == 'do_not_adopt_heldout_gate_failed'
