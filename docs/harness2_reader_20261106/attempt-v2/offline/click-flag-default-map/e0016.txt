# Tool Usage Guidelines

## read_file
- **Purpose**: Read file content for analysis.
- **Arguments**: `path` (required), `offset` (optional, default 0).
- **Failure Modes**: 
  - File not found: Check path spelling and existence.
  - Invalid offset: Ensure offset is non-negative and within file bounds.

## search
- **Purpose**: Find text patterns across files.
- **Arguments**: `query` (required), `path_glob` (optional, default "*.py").
- **Failure Modes**: 
  - No matches: Refine query or expand `path_glob`.
  - Truncated results: Use `offset` in subsequent reads if needed.

## apply_patch
- **Purpose**: Submit code changes.
- **Arguments**: `edits` (array of `{file, old, new}`).
- **Failure Modes**:
  - `invalid_patch_schema`: Ensure `edits` is an array with required fields.
  - `anchor_not_found`: Verify `old` text exists exactly once in the target file.
  - `repeated_action_limit`: Avoid identical retries; diagnose root cause first.

## General Rules
- Always trace tool errors to specific trajectory moments before retrying.
- Prefer bounded fallbacks over blind repetition (e.g., adjust query, check file existence).
- Do not assume test outcomes; rely on actual validation feedback.