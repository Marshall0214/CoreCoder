# Tool Usage Guidance

## read_file
- **Purpose**: Read the content of a specific file.
- **Usage**: Use this tool to inspect source code files, test files, and documentation.
- **Parameters**:
  - `path`: The path to the file to read (e.g., "toolz/itertoolz.py").
  - `offset`: The starting offset for reading (useful for large files).

## search
- **Purpose**: Search for a specific query within files matching a pattern.
- **Usage**: Use this tool to locate functions, variables, or specific code patterns across the codebase.
- **Parameters**:
  - `query`: The search term or regex pattern.
  - `path_glob`: The file pattern to search (e.g., "*.py").

## list_files
- **Purpose**: List files in a directory matching a pattern.
- **Usage**: Use this tool to explore the directory structure and identify relevant files.
- **Parameters**:
  - `pattern`: The file pattern to match (e.g., "*.py").
  - `offset`: The starting offset for listing (useful for large directories).

# Best Practices
- Always verify the existence of a file before attempting to read it.
- Use `search` to quickly locate specific functions or variables before reading entire files.
- When reading large files, use the `offset` parameter to navigate efficiently.