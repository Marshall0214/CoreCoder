import ast
import json

import pytest

from evals.check_review import reviewed_checks
from evals.schema import RunConfig
from tests.test_contract_feedback import CODE, patch, setup_run


def entry(name="Public.test_value", verdict="accept"):
    return {"test": name, "verdict": verdict, "evidence_file": "description",
            "evidence_quote": "value() must return 3", "reason": "The public contract requires value 3.",
            "numeric_proofs": [{"assertion": 0, "expression": "1 + 2"}] if verdict == "accept" else []}


def test_review_filters_rejected_and_uncertain_methods_without_rewriting_assertions():
    code = CODE + "    def test_wrong(self):\n        self.assertEqual(value(), 1)\n" + (
        "    def test_unknown(self):\n        self.assertEqual(value(), 9)\n")
    reviews = [entry(), entry("Public.test_wrong", "reject"), entry("Public.test_unknown", "uncertain")]
    filtered, ledger = reviewed_checks(json.dumps({"reviews": reviews}), code, "value() must return 3", [])
    assert [item["verdict"] for item in ledger] == ["accept", "reject", "uncertain"]
    assert ledger[0]["numeric_validation"][0]["computed"] == "3"
    assert "test_wrong" not in filtered and "test_unknown" not in filtered
    original_assertion = next(n for n in ast.walk(ast.parse(CODE)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute))
    retained_assertion = next(n for n in ast.walk(ast.parse(filtered)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute))
    assert ast.dump(original_assertion) == ast.dump(retained_assertion)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "bad_verdict"])
def test_invalid_review_cannot_authorize_checks(mutation):
    reviews = [entry()]
    if mutation == "missing":
        reviews = []
    elif mutation == "duplicate":
        reviews *= 2
    elif mutation == "unknown":
        reviews[0]["test"] = "Public.test_missing"
    else:
        reviews[0]["verdict"] = "probably"
    with pytest.raises(ValueError):
        reviewed_checks(json.dumps({"reviews": reviews}), CODE, "value() must return 3",
                        [{"path": "value.py", "content": "value() must return 3"}])


@pytest.mark.parametrize("field,value", [("evidence_quote", "Invented behavior"), ("evidence_file", "value.py")])
def test_unsupported_citation_rejects_only_the_affected_method(field, value):
    code = CODE + "    def test_other(self):\n        self.assertEqual(value(), 3)\n"
    bad, good = entry(), entry("Public.test_other")
    bad[field] = value
    filtered, ledger = reviewed_checks(json.dumps({"reviews": [bad, good]}), code, "value() must return 3",
                                        [{"path": "value.py", "content": "value() must return 3"}])
    assert ledger[0]["verdict"] == "reject" and "citation_error" in ledger[0]
    assert ledger[1]["verdict"] == "accept"
    assert "def test_value" not in filtered and "def test_other" in filtered


def test_reviewed_workflow_runs_review_before_patch_and_execution(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [entry()]},
                                        patch("return 1", "return 2"), patch("return 2", "return 3")],
                              public_check_policy="reviewed")
    assert result["protocol"] == "public-contract-feedback-v2-review"
    assert result["public_checks"]["final"]["passed"] and len(llm.messages) == 4
    review_input = json.loads(llm.messages[1][1]["content"])
    assert set(review_input) == {"description", "files", "code", "tests", "numeric_assertions"}
    assert "return 1" in json.dumps(review_input)
    assert "return 2" not in json.dumps(review_input) and "output" not in review_input
    records = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    kinds = [r["event"] for r in records]
    assert kinds.index("public_contract_reviewed") < kinds.index("public_contract_frozen") < kinds.index("public_contract_checked")


@pytest.mark.parametrize("review", [{"reviews": [entry(verdict="reject")]}, {"reviews": []}])
def test_rejected_or_invalid_review_disables_feedback_but_allows_initial_patch(tmp_path, review):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, review, {"edits": []}], public_check_policy="reviewed")
    assert result["status"] == "completed" and result["feedback_attempts"] == 0
    assert len(llm.messages) == 3 and "original" not in result["public_checks"]
    assert not (tmp_path / "public-contract-checks.py").exists()
    assert (tmp_path / "public-contract-generated.py").exists()


def test_reviewer_acceptance_does_not_claim_semantic_proof(tmp_path):
    wrong = CODE.replace("value(), 3", "value(), 1")
    accepted = entry()
    accepted["numeric_proofs"][0]["expression"] = "1"
    result, _, _ = setup_run(tmp_path, [{"code": wrong}, {"reviews": [accepted]}, {"edits": []}],
                             public_check_policy="reviewed")
    assert result["public_checks"]["candidate"]["passed"]
    assert result["public_checks"]["semantic_correctness_verified"] is False
    assert "accepted" not in result


def test_review_configuration_is_opt_in():
    assert RunConfig().public_check_policy == "generated"
    with pytest.raises(ValueError):
        RunConfig(mode="pipeline", search_backend="keyword", public_check_policy="reviewed")


def test_model_acceptance_with_wrong_arithmetic_cannot_authorize_feedback(tmp_path):
    accepted = entry()
    accepted["numeric_proofs"][0]["expression"] = "round_half_up(100 * 5 / 10000)"
    result, llm, _ = setup_run(tmp_path, [{"code": CODE.replace("value(), 3", "value(), 1")},
                                        {"reviews": [accepted]}, {"edits": []}], public_check_policy="reviewed")
    checks = result["public_checks"]
    assert checks["reviews"][0]["model_verdict"] == "accept"
    assert checks["reviews"][0]["verdict"] == "reject"
    assert "differs from expected" in checks["reviews"][0]["numeric_error"]
    assert result["feedback_attempts"] == 0 and len(llm.messages) == 3
