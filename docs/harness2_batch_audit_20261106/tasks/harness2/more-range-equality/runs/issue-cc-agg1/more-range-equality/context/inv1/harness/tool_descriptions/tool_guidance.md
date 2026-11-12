# Tool Guidance

## `apply_patch`
- **Purpose**: Apply changes to source files.
- **Schema**: 
  ```json
  {
    "edits": [
      {
        "file": "path/to/file.py",
        "old": "exact string to replace",
        "new": "replacement string"
      }
    ]
  }
  ```
- **Common Errors**:
  - `invalid_patch_schema`: Ensure `edits` is an array and each edit has `file`, `old`, `new` as strings.
  - `anchor_not_found`: The `old` string must match exactly once in the current source. Check for whitespace, indentation, or content differences.
- **Strategy**: 
  1. Read the specific symbol or file section to get the exact text.
  2. Construct the `old` string precisely from the read output.
  3. Apply the patch.

## `read_symbol`
- **Purpose**: Retrieve a specific function, class, or method definition.
- **Usage**: Use when you need the exact code of a symbol to construct a patch anchor.
- **Output**: Returns `content` which should be used verbatim for the `old` field in `apply_patch`.

## `read_file`
- **Purpose**: Read file content with offset support.
- **Usage**: Use when `read_symbol` is insufficient or you need context around a symbol.
- **Note**: Large files may require multiple reads with increasing offsets. Check `next_offset` in the response.

# Workspace-Specific Guidance
- **Attribute Names**: In `more_itertools/more.py`, the `numeric_range` class uses `_len` (cached property) for length, not `_length`. Any code referencing `_length` is incorrect.
- **Equality Logic**: For `numeric_range.__eq__`, ensure singleton ranges (length 1) compare equal if their start values are equal, regardless of step. Use `self._len` to check length.