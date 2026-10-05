"""Contract-driven contrast scenarios; no task IDs, grader data or reference edits."""

PROTOCOL = 'public-contract-feedback-v6-scenarios'
GENERATION_RULES = (
    ' Prioritize small contrast scenarios that distinguish the stated behavior from plausible defects, '
    'not just happy-path examples. Derive scenarios only from the public contracts supplied for this task. '
    'When uniqueness is scoped, reuse exactly the same identifier in two different scopes. '
    'When duplicate inputs must not prevent later processing, put a duplicate BEFORE a distinct later input '
    'and assert the later input contributes. When state persists across calls, reuse the same state and '
    'bookkeeping arguments for successive calls, replay an earlier input and append a new one. '
    'Observe API return values, never bookkeeping representations. If returned containers may mutate in '
    'later calls, capture independent shallow snapshots immediately using dict(result) or list(result) '
    'for flat containers, and assert snapshots only after the calls. Keep input state variables separate '
    'from return/snapshot variables; do not pass the asserted snapshot into another API call. '
    'Do not invent scoping, persistence or duplicate behavior absent from the contract. '
    'Use at most six short tests; cover the reported contract interactions before spending tests on '
    'single-record happy paths. These examples are test-design guidance, not extra task requirements.'
)
