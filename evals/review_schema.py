"""Provider output constraints supplement, but never replace, local review validation."""

import json
import re

from .check_arithmetic import numeric_assertions
from .check_review import test_methods

PROTOCOL = "public-contract-feedback-v4-schema"
EXPRESSION_PATTERN = r"^[0-9a-z_+*/()., -]+$"


def review_response_format(code, catalog):
    if not catalog:
        raise ValueError("Structured review needs a nonempty public contract catalog")
    names = test_methods(code)
    assertions = numeric_assertions(code)
    indices = sorted({item["assertion"] for rows in assertions.values() for item in rows})
    proof = {"type": "object", "additionalProperties": False, "required": ["assertion", "expression"],
             "properties": {"assertion": {"type": "integer", "enum": indices or [0]},
                            "expression": {"type": "string", "minLength": 1, "maxLength": 180,
                                           "pattern": EXPRESSION_PATTERN}}}
    row = {"type": "object", "additionalProperties": False,
           "required": ["test", "verdict", "contract_ids", "reason_code", "numeric_proofs"],
           "properties": {
               "test": {"type": "string", "enum": names},
               "verdict": {"type": "string", "enum": ["accept", "reject", "uncertain"]},
               "contract_ids": {"type": "array", "maxItems": 8,
                                "items": {"type": "string", "enum": [item["id"] for item in catalog]}},
               "reason_code": {"type": "string", "enum": ["consistent", "contradiction", "missing_contract",
                                                            "arithmetic", "units", "api_mismatch"]},
               "numeric_proofs": {"type": "array", "maxItems": max(map(len, assertions.values()), default=0),
                                  "items": proof}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["reviews"],
              "properties": {"reviews": {"type": "array", "minItems": len(names), "maxItems": len(names),
                                         "items": row}}}
    return {"type": "json_schema", "json_schema": {"name": "public_contract_review", "strict": True, "schema": schema}}


def validate_pure_expressions(content):
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("reviews"), list):
        raise ValueError("Expected reviews array")  # noqa: TRY004 - review validation uses ValueError
    for row in parsed["reviews"]:
        if not isinstance(row, dict) or not isinstance(row.get("numeric_proofs"), list):
            raise ValueError("Expected numeric_proofs array")  # noqa: TRY004 - review validation uses ValueError
        for proof in row["numeric_proofs"]:
            expression = proof.get("expression") if isinstance(proof, dict) else None
            if (not isinstance(expression, str) or not 1 <= len(expression) <= 180
                    or not re.fullmatch(EXPRESSION_PATTERN, expression)):
                raise ValueError("Schema review requires bounded pure expressions without equalities")
