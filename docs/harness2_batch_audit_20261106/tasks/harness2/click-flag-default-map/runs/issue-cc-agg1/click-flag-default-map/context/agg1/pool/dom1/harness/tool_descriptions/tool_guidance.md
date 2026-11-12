# Tool Guidance for Click Defect Repair

## read_file
Use `read_file` to inspect `src/click/core.py` and `src/click/formatting.py`. Focus on:
- The `Option` class definition.
- The `get_help_record` method or equivalent logic that formats help strings.
- How `default_map` is accessed within the context (`ctx`).

## search
Use `search` with query `"default_map"` and path_glob `*.py` to locate all references to default map handling. This helps identify where the override logic might be missing or incorrect.

## apply_patch
When proposing a fix:
- Ensure the patch targets the exact location where help text is generated.
- The fix must ensure that if `ctx.default_map` contains an entry for the option, the help text reflects the *effective* default (e.g., `slow` instead of `fast`).
- Verify the patch against the test case: `test_public_defect` expects `[default: slow]` when `default_map` overrides to `False`.

## Validation
Before finalizing, ensure:
- The fix does not break existing tests (e.g., `test_public_normal_behavior`).
- The help output matches the effective default derived from `default_map`.