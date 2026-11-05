# Tool Usage Guidance

## File Reading Strategy
- **Target**: `toolz/itertoolz.py` is the primary file for this task.
- **Search**: Use `search` with query `def join` to locate the function start immediately.
- **Read**: Read the full function definition. If the file is large, read in chunks starting from the function definition until the end of the function body is reached.

## Defect Pattern Recognition
- **Symptom**: `NameError` during a left outer join operation.
- **Cause**: The code path for unmatched left rows references a variable (likely `right_default` or similar) that is only defined in the matched branch or not at all.
- **Fix Location**: Inside the loop iterating over left keys, specifically in the `else` block or conditional handling the case where no right match is found.

## Evidence-Based Repair
- **Do not guess** the variable name. Inspect the existing code to see what variable holds the default value (e.g., `right_default`, `default_right`, or a parameter passed to the function).
- **Ensure scope**: The variable must be accessible in the branch where unmatched rows are yielded.

# Workspace Facts (Verified)
- **File**: `toolz/itertoolz.py` contains the `join` function.
- **Defect**: Left outer join yields `NameError` for unmatched left rows.
- **Requirement**: Matched rows and inner joins must remain unchanged.