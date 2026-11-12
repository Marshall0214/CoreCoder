# Tool Usage Guidance for Click Defect Repair

## Reading Source Code
- Use `read_file` with specific offsets to inspect `src/click/core.py`, particularly around lines 760-1250 where `Context.invoke` and parameter handling reside.
- Use `search` to find all occurrences of `UNSET`, `Sentinel`, or similar sentinel values in the codebase.
- When `read_symbol` returns ambiguous results, use `read_file` with line numbers from the search results to inspect specific implementations.

## Patching
- Ensure patches target the exact location where the sentinel is returned or passed.
- The patch must change the return value or argument passing logic to use `None` instead of the sentinel for omitted optional parameters.
- Verify that the patch does not break existing functionality by checking that explicit arguments and defaults still work correctly.

## Testing
- The primary test to pass is `test_public_defect` which checks that `ctx.invoke(cli)` returns `None`.
- Ensure `test_public_normal_behavior` continues to pass, confirming that normal invocation with provided arguments works as expected.