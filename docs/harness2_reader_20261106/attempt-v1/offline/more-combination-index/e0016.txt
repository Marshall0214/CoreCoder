# Tool Guidance for Python Defect Repair

## read_file / read_symbol
- **Purpose**: Inspect source code to understand current implementation.
- **Usage**: Always read the full symbol or file before editing. Use `read_symbol` for functions/classes to get complete context including docstrings and logic.
- **Fallback**: If a symbol is not found, fall back to `read_file` on the containing module.

## search
- **Purpose**: Locate occurrences of functions, variables, or patterns across the codebase.
- **Usage**: Use when the target function name is known but location is uncertain. Search results include line numbers and file paths.
- **Fallback**: If no matches found, verify spelling or broaden the query (e.g., remove quotes).

## apply_patch
- **Purpose**: Submit precise code changes to fix defects.
- **Usage**: Provide exact `old` and `new` text blocks. Ensure indentation and whitespace match the original file.
- **Validation**: The patch must be syntactically valid Python and preserve all imports and dependencies.
- **Edge Cases**: Explicitly handle empty inputs, None values, and invalid combinations as required by the task.

## list_files
- **Purpose**: Discover available files in the workspace.
- **Usage**: Use with glob patterns (e.g., `*.py`) to identify relevant modules before reading.
- **Fallback**: If no files match, verify the pattern or check for typos in file extensions.