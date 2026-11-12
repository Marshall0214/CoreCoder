# Tool Guidance for Python Repair

## File Reading Strategy
- **Targeted Reads**: Use `read_file` with specific offsets to locate function definitions. Avoid reading entire files unless necessary.
- **Symbol Navigation**: If available, use symbol-based navigation to jump directly to function definitions (e.g., `def remap`).

## Evidence Verification
- **Cross-Reference**: Always verify function behavior against the task requirements (e.g., "preserve set values", "preserve frozenset type").
- **Trace Execution**: Manually trace the logic of the function to identify where it deviates from expected behavior.

## Repair Actions
- **Minimal Changes**: Modify only the lines necessary to fix the defect. Avoid refactoring unrelated code.
- **Preserve Semantics**: Ensure that changes do not alter the intended behavior for other data types (e.g., lists, dictionaries).

# Skill Invocation
When the task involves repairing `remap` in `boltons/iterutils.py`, invoke the `remap-repair` skill to apply domain-specific checks and fixes.