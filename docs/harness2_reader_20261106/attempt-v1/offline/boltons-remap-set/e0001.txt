The base rollout (base1.md) failed due to a syntax error in the candidate patch (`misc/bench_omd.py`, `misc/linkify_changelog.py`), but more critically, it did not address the core defect in `boltons/iterutils.py` as described in `task.md`. The agent repeatedly read the same offset (7000) without making progress, leading to a `repeated_action_limit` error. 

The task explicitly requires `remap` to preserve set/frozenset values and types without inserting key-value pairs. The current harness lacks any guidance on this specific behavior or the file structure of `boltons/iterutils.py`. 

Changes made:
1. **systemprompt.md**: Added a &#x27;Workspace Facts&#x27; section with verified constraints from `task.md` (preserve set/frozenset, no key-value insertion). Added a trigger line for the new skill.
2. **tool_descriptions/tool_guidance.md**: Added specific guidance on reading strategies and evidence verification for Python repair tasks, emphasizing targeted reads and cross-referencing against task requirements.
3. **context_policy.json**: Updated to `version: 1`, enabled `deduplicate_reads` (to prevent the repeated offset reading seen in base1), enabled `complete_symbols_first` (to encourage finding function definitions before reading arbitrary offsets), and enabled `read_index` (to leverage file structure if available).

These changes directly address the observed failure modes: lack of domain-specific constraints, inefficient reading strategy, and missing procedural guidance for the specific defect.