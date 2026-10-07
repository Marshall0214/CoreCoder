import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from docs.experiments import salt_relations_audit_v1 as audit


@pytest.fixture
def public_case(tmp_path):
    description = next(t['description'] for t in json.loads((audit.ROOT / 'docs/experiments/second-repo-public-tasks-v1.json').read_text(encoding='utf-8'))['tasks'] if t['task_id'] == audit.TASK)
    for filename, owner, default in [('serializer.py', 'Serializer', 'itsdangerous'), ('signer.py', 'Signer', 'itsdangerous.Signer')]:
        path = tmp_path / 'src/itsdangerous' / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"class {owner}:\n    def __init__(self, secret, salt=b'{default}'):\n        self.salt = salt\n", encoding='utf-8')
    return {'before': tmp_path, 'description': description}


def test_contract_has_exact_public_spans_and_distinct_default_sources(public_case):
    record = audit.contract(public_case)
    for row in record['clauses']:
        start, end = row['span']
        assert public_case['description'][start:end] == row['text']
    assert record['original_api_defaults']['Signer']['salt_utf8'] != record['original_api_defaults']['Serializer']['salt_utf8']
    assert len(record['rules']) == 4 and record['check_sha256'] == audit.repair.audit.sha(audit.CHECK)


@pytest.mark.parametrize('changed', ["b'changed'", 'None'])
def test_changed_original_default_rejected(public_case, changed):
    path = public_case['before'] / 'src/itsdangerous/serializer.py'
    path.write_text(path.read_text(encoding='utf-8').replace("b'itsdangerous'", changed), encoding='utf-8')
    with pytest.raises((ValueError, TypeError), match='defaults'):
        audit.contract(public_case)


@pytest.mark.parametrize('count', [0, 2])
def test_mutation_missing_or_ambiguous_anchor_does_not_write(tmp_path, count):
    spec = audit.MUTATIONS['omitted_default_changed']
    path = tmp_path / spec[0]
    path.parent.mkdir(parents=True)
    path.write_text(spec[1] * count, encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='unique'):
        audit.mutate(tmp_path, spec)
    assert path.read_bytes() == before


@pytest.fixture
def checks(monkeypatch):
    class BadSignature(Exception):
        pass
    monkeypatch.setitem(sys.modules, 'itsdangerous', SimpleNamespace(BadSignature=BadSignature, Serializer=object, Signer=object))
    spec = importlib.util.spec_from_file_location('public_salt_checks_test', audit.CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PublicContract(), BadSignature


@pytest.mark.parametrize('kind', ['type', 'value', 'signature'])
def test_expected_domain_failures_are_assertions(checks, kind):
    test, bad_signature = checks
    error = {'type': TypeError, 'value': ValueError, 'signature': bad_signature}[kind]
    def fail():
        raise error('broken public relation')
    with pytest.raises(AssertionError, match='expects successful'):
        test.expected_success(fail)


def test_unexpected_execution_error_is_not_semantic_failure(checks):
    test, _ = checks
    def fail():
        raise RuntimeError('infrastructure or unexpected execution error')
    with pytest.raises(RuntimeError):
        test.expected_success(fail)


def test_existing_audit_output_rejected_before_loading_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(audit.public.comparison, 'prepare', lambda _: pytest.fail('Must reject before reading inputs'))
    with pytest.raises(ValueError, match='fresh'):
        audit.audit(tmp_path)
