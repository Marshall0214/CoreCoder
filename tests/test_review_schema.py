
import pytest

from corecoder.llm import LLM, LLMResponse
from evals.context_policy import request_breakdown
from evals.contract_catalog import contract_catalog
from evals.review_schema import review_response_format, validate_pure_expressions
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig
from evals.worker import TracedLLM
from tests.test_contract_catalog import review
from tests.test_contract_feedback import CODE, patch, setup_run


def test_schema_limits_names_contracts_and_expression_syntax():
    response_format = review_response_format(CODE, contract_catalog("value() must return 3", []))
    schema = response_format["json_schema"]["schema"]
    rows = schema["properties"]["reviews"]
    assert rows["minItems"] == rows["maxItems"] == 1
    fields = rows["items"]["properties"]
    assert fields["test"]["enum"] == ["Public.test_value"]
    assert fields["contract_ids"]["items"]["enum"] == ["c0001"]
    assert rows["items"]["additionalProperties"] is False


def test_schema_applies_only_to_review_and_preserves_bounded_feedback(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [review()]},
                                        patch("return 1", "return 2"), patch("return 2", "return 3")],
                              public_check_policy="contract-schema")
    assert result["protocol"] == "public-contract-feedback-v4-schema"
    assert result["public_checks"]["final"]["passed"] and result["feedback_attempts"] == 1
    assert [bool(options) for options in llm.options] == [False, True, False, False]
    assert llm.options[1]["response_format"]["type"] == "json_schema"
    assert (tmp_path / "public-check-review-format.json").exists()
    assert result["public_checks"]["review_schema_hash"]


@pytest.mark.parametrize("expression", ["1+2=3", "1+2=3=3", "unbounded prose!", "x" * 181])
def test_provider_ignoring_expression_constraints_disables_review(tmp_path, expression):
    item = review()
    item["numeric_proofs"][0]["expression"] = expression
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [item]}, {"edits": []}],
                              public_check_policy="contract-schema")
    assert result["status"] == "completed" and result["feedback_attempts"] == 0
    assert result["public_checks"]["review_status"] == "invalid" and len(llm.messages) == 3


def test_format_estimate_is_included_without_changing_old_estimates():
    messages = [{"role": "user", "content": "public contract"}]
    before = request_breakdown(messages, [])
    after = request_breakdown(messages, [], response_format={"schema": "x" * 100})
    assert "response_format_estimate" not in before
    assert after["request_estimate"] == before["request_estimate"] + after["response_format_estimate"]


def test_schema_budget_blocks_before_provider_call(tmp_path):
    class Provider:
        model = "test"

        def chat(self, *args, **kwargs):
            pytest.fail("Over-budget schema must not reach provider")

    llm = BudgetLLM(Provider(), RunConfig(token_budget=100, max_output_tokens=16, context_tokens=200),
                    Events(tmp_path / "trace.jsonl", "test"))
    with pytest.raises(BudgetExceeded):
        llm.chat([{"role": "user", "content": "x"}], response_format={"schema": "x" * 1000})
    assert llm.calls == 0


@pytest.mark.parametrize("fail", [False, True])
def test_provider_extra_is_restored_after_success_or_error(monkeypatch, fail):
    llm = object.__new__(TracedLLM)
    original = {"max_tokens": 2048}
    llm.extra = original
    seen = []

    def mocked_chat(self, *args, **kwargs):
        seen.append(dict(self.extra))
        if fail:
            raise RuntimeError("Unsupported format")
        return LLMResponse(content="{}")

    monkeypatch.setattr(LLM, "chat", mocked_chat)
    if fail:
        with pytest.raises(RuntimeError):
            llm.chat([], response_format={"type": "json_schema"})
    else:
        llm.chat([], response_format={"type": "json_schema"})
    assert seen[0]["response_format"] == {"type": "json_schema"}
    assert llm.extra is original and "response_format" not in llm.extra


def test_schema_does_not_imply_semantic_correctness(tmp_path):
    item = review()
    item["numeric_proofs"][0]["expression"] = "1"
    result, _, _ = setup_run(tmp_path, [{"code": CODE}, {"reviews": [item]}, {"edits": []}],
                             public_check_policy="contract-schema")
    assert result["public_checks"]["accepted_tests"] == []
    assert result["public_checks"]["semantic_correctness_verified"] is False


def test_malformed_json_is_not_repaired():
    with pytest.raises(ValueError):
        validate_pure_expressions('{"reviews":[')
    with pytest.raises(ValueError):
        review_response_format(CODE, [])
