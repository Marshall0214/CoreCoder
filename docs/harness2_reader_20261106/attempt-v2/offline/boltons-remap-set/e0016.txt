# Tool Usage Guidance

## File Reading
- Use `read_file` with explicit `offset` and `path` arguments to inspect source code.
- If a file is large, read in chunks (e.g., offset 0, then 7000) to avoid truncation.
- Verify content hashes match expected values if available.

## File Writing
- Use `write_file` only after verifying the fix logic against task requirements.
- Do not assume a successful write call establishes usability; validate the artifact survives conversion (e.g., via `candidate.diff`).

## Search
- Use `search` with `query` and `path_glob` to locate functions or patterns (e.g., "def remap" in "*.py").
- Confirm matches before reading files.

## Error Handling
- Distinguish between:
  - **Bad Input**: Invalid arguments to tools.
  - **Timeout**: Tool execution exceeded time limit.
  - **Missing Capability**: Tool does not support required operation.
  - **Permission**: Access denied to file or resource.
  - **Unread Output**: Tool output truncated or malformed.
- Provide one bounded fallback (e.g., retry once with adjusted parameters) and a stop condition (e.g., "stop after 2 retries").

## Mechanical Repetition
- For repeated deterministic tasks (e.g., validating set preservation), use `scripts/<name>.py`:
  - Define clear inputs, outputs, and failure behavior.
  - Example: A script that checks if `frozenset` types are preserved after `remap`.

## Triggered Workflows
- Use skills for narrow multi-step procedures (e.g., "fix_remap_defect").
- Name the skill in always-on text with a trigger line:
  > When fixing the remap defect, load the `fix_remap_defect` skill.
- Carry any helper scripts or subagents required by the skill.

## Ignored Invariants
- Only use `plugin/<name>.ts` hooks if repeated evidence shows clear prose is skipped (e.g., agent exits before deliverable exists).
- Hooks must not block valid completion.

## Ordinary Sequencing
- Prefer concise always-on guidance for common steps.
- Do not add code for one-off mistakes or automate professional judgment.

# Validation Checklist
1. **Skill Trigger**: Every skill has a trigger line in `systemprompt.md` or `guardrails.md`.
2. **No Template Braces**: Always-on text contains no `{{`, `{%`, or similar Jinja syntax.
3. **Script Existence**: Every script named in skills or always-on text exists in the proposal.
4. **Deliverable Shape**: The artifact matches task specifications exactly (no added columns, renamed headers, or intermediate values).
5. **Usability Check**: Verify the artifact survives conversion (e.g., `candidate.diff` is readable and correct).