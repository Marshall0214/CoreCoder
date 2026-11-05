# Tool Usage Guidance

## File Reading Strategy
- **Search First**: Always use `search` with query `def <function_name>` to locate the target function before reading.
- **Read Complete Symbols**: When reading a function, ensure you read from the definition line until the end of the function body. Avoid partial reads that miss critical logic (e.g., reading offset 800 when the function starts at 813).
- **Avoid Redundant Reads**: Do not repeat `read_file` on the same offset without progress. If you receive a `repeated_action_limit`, stop and change strategy.

## Defect Pattern Recognition
- **Symptom**: `NameError` during a left outer join operation.
- **Cause**: The code path for unmatched left rows references a variable (likely `right_default`) that is not initialized in the scope of the unmatched branch.
- **Fix Location**: Inside the loop iterating over left keys, specifically in the conditional handling the case where no right match is found.

## Evidence-Based Repair
- **Do not guess** the variable name. Inspect the existing code to see what variable holds the default value.
- **Ensure scope**: The variable must be accessible in the branch where unmatched rows are yielded.