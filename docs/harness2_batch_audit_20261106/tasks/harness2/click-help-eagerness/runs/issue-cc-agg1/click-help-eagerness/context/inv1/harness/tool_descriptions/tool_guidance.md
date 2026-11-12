# Tool Guidance

## read_file / read_symbol
- **Purpose**: Retrieve source code content.
- **Usage**: Prefer `read_symbol` for functions/classes to get complete, context-aware blocks. Use `read_file` with `offset` for large files or when symbol boundaries are unclear.
- **Fallback**: If `read_symbol` fails or returns incomplete data, fall back to `read_file` with a calculated offset based on line numbers from search results.

## search
- **Purpose**: Locate specific strings or patterns across the codebase.
- **Usage**: Use `query` for exact matches and `path_glob` to limit scope (e.g., `*.py`).
- **Fallback**: If no matches are found, broaden the query or check for typos in variable names.

## apply_patch
- **Purpose**: Modify source files.
- **Usage**: Provide an `edits` array where each edit has `file`, `old` (exact match), and `new` (replacement) fields.
- **Critical Rule**: The `old` text must occur exactly once in the current source. If `anchor_not_found` occurs, re-read the file/symbol to get the exact current content before retrying.
- **Fallback**: On schema errors (`invalid_patch_schema`), verify the JSON structure matches `{"edits": [{"file": "...", "old": "...", "new": "..."}]}` exactly. Do not add extra keys.