# Tool Guidance for Python Defect Repair

## read_file

**When to use**: Inspecting source files, understanding function implementations, locating error sites.

**Best practices**:
- Always specify exact `offset` and `length` parameters.
- For large files, read in chunks (max 6000 characters per request).
- Use the evidence index to find file IDs before reading.
- Read complete function definitions when analyzing behavior.

## search

**When to use**: Locating specific functions, patterns, or error sites across the codebase.

**Best practices**:
- Use targeted search terms (function names, variable names, error messages).
- Combine with `read_file` to inspect full context of matches.

## write_file / edit_file

**When to use**: Applying fixes after evidence-based analysis.

**Best practices**:
- Only modify what trajectory evidence shows is broken.
- Preserve existing behavior for unaffected code paths.
- Ensure the fix addresses the exact error (e.g., `NameError` → replace undefined name with correct one).

## Validation Checklist

Before submitting:
1. Does the fix resolve the specific error in the trajectory?
2. Are matched rows and inner joins preserved?
3. Do unmatched left rows receive `right_default`?
4. No new static findings introduced (F821, F822, F823)?
5. Tests pass without errors?