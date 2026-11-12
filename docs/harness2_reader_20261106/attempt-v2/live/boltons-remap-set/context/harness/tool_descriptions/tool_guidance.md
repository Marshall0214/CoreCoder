# Tool Guidance for Python Repair

## File Reading Strategy
- **Targeted Reads**: Use `read_file` with specific offsets to locate function definitions. Avoid reading entire files unless necessary.
- **Symbol Navigation**: If available, use symbol-based navigation to jump directly to function definitions (e.g., `def remap`).

## Evidence Verification
- **Cross-Reference**: Verify function behavior against task requirements (e.g., "preserve set values", "preserve frozenset type").
- **Trace Execution**: Manually trace logic to identify deviations from expected behavior.

## Repair Actions
- **Minimal Changes**: Modify only lines necessary to fix the defect. Avoid refactoring unrelated code.
- **Preserve Semantics**: Ensure changes do not alter intended behavior for other data types (e.g., lists, dictionaries).

# Skill Invocation
When repairing `remap` in `boltons/iterutils.py`, invoke the `remap-repair` skill to apply domain-specific checks and fixes.