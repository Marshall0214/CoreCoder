import json

import pytest

from evals.check_review import reviewed_checks
from evals.contract_catalog import contract_catalog, public_interfaces
from tests.test_contract_feedback import CODE, patch, setup_run


def review(ids=None):
    return {"test": "Public.test_value", "verdict": "accept", "contract_ids": ["c0001"] if ids is None else ids,
            "reason_code": "consistent", "numeric_proofs": [{"assertion": 0, "expression": "1 + 2"}]}


def test_catalog_is_deterministic_and_preserves_line_provenance():
    evidence = [{"path": "docs/z.md", "content": "# Z\n\nKeep Z.\n"},
                {"path": "docs/a.md", "content": "Keep A.\n"}, {"path": "x.py", "content": "secret"}]
    catalog = contract_catalog("public behavior", evidence)
    assert catalog == contract_catalog("public behavior", list(reversed(evidence)))
    assert catalog[0] == {"id": "c0001", "source": "description", "line": 1, "text": "public behavior"}
    assert catalog[-1]["line"] == 3 and catalog[-1]["text"] == "Keep Z."
    assert "secret" not in json.dumps(catalog)


def test_interfaces_exclude_bodies_defaults_annotations_and_decorators():
    source = ('PRIVATE = "body-sentinel"\n@decorator("decorator-sentinel")\n'
              'def value(x: "annotation-sentinel", /, y="default-sentinel", *args, z=99, **kwargs):\n'
              '    "doc-sentinel"\n    return "body-sentinel"\n'
              'class Public:\n    async def get(self, key):\n        return "class-sentinel"\n')
    metadata = public_interfaces([{"path": "api.py", "content": source}])
    encoded = json.dumps(metadata)
    assert "sentinel" not in encoded and "99" not in encoded
    parameters = metadata[0]["symbols"][0]["parameters"]
    assert parameters[0] == {"name": "x", "kind": "positional_only", "has_default": False}
    assert parameters[1]["has_default"] and parameters[3]["kind"] == "keyword_only"
    assert metadata[0]["symbols"][1]["async"]


def test_invalid_source_interface_reports_error_without_body():
    assert public_interfaces([{"path": "api.py", "content": "broken sentinel !"}]) == [
        {"path": "api.py", "symbols": [], "parse_error": True}]


@pytest.mark.parametrize("ids", [[], ["unknown"], ["c0001", "unknown"]])
def test_missing_or_unknown_ids_cannot_authorize_test(ids):
    description = "value() must return 3"
    code, ledger = reviewed_checks(json.dumps({"reviews": [review(ids)]}), CODE, description, [],
                                    catalog=contract_catalog(description, []))
    assert code is None and ledger[0]["verdict"] == "reject"


def test_duplicate_ids_are_structural_error():
    with pytest.raises(ValueError, match="Invalid contract IDs"):
        reviewed_checks(json.dumps({"reviews": [review(["c0001", "c0001"])]}), CODE, "value() must return 3", [],
                        catalog=contract_catalog("value() must return 3", []))


def test_contract_only_review_preserves_feedback_and_avoids_implementation_inputs(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [review()]},
                                        patch("return 1", "return 2"), patch("return 2", "return 3")],
                              public_check_policy="contract-only")
    data = json.loads(llm.messages[1][1]["content"])
    assert set(data) == {"contract_catalog", "interfaces", "code", "tests", "numeric_assertions"}
    assert "return 1" not in json.dumps(data) and "return 2" not in json.dumps(data)
    assert result["protocol"] == "public-contract-feedback-v3-contract-only"
    assert result["public_checks"]["final"]["passed"] and result["feedback_attempts"] == 1
    assert result["public_checks"]["reviews"][0]["resolved_contracts"][0]["text"] == "value() must return 3"
    assert json.loads((tmp_path / "public-check-review-input.json").read_text()) == data


def test_catalog_limits_fail_without_truncation():
    with pytest.raises(ValueError, match="no silent truncation"):
        contract_catalog("x\n" * 161, [])


def test_invalid_reason_code_is_review_error_not_worker_crash(tmp_path):
    item = review()
    item["reason_code"] = []
    result, _, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [item]}, {"edits": []}],
                             public_check_policy="contract-only")
    assert result["status"] == "completed"
    assert result["public_checks"]["review_status"] == "invalid" and result["feedback_attempts"] == 0
