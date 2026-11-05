# Evidence-only failure review

No Agent/validator/runtime code changed, no new model calls and no new test execution. The four requested material groups preserve original source, the exact final patch, complete Target test/error, and effective requests/responses around reading and patch generation. Whole-file copies preserve byte hashes; function extracts normalize line endings and identify original line ranges in evidence-findings.json.

The prior Docker counterfactuals were performed on the earlier trial candidate, not rerun on this one. The two candidates have identical Python ASTs (ignoring source locations/comments) and use identical checks; this supports comparison while keeping the original execution provenance distinct. No hidden grading feedback was supplied to the Agent. Source fragments retain Toolz-LICENSE.txt.

The effective requests are after strategy/context processing. Structured responses do not expose internal reasoning. Original confidence/adoption is not validation, and this review does not establish generalization or a new repair score. Previous evidence packets remain unchanged.
