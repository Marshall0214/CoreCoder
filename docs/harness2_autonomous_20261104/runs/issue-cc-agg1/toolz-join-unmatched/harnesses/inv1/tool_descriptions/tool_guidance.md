# Tool Usage Guidance

## File Operations
- **list_files**: Use with `pattern` and `offset` to discover relevant Python files. Start with broad patterns (e.g., `*.py`) and narrow down.
- **read_file**: Use `path` and `offset` to inspect code. If the file is large, read in chunks. Note that repeated reads of the same offset without progress may trigger a limit.
- **search**: Use `query` and `path_glob` to find specific function definitions or keywords quickly.

## Error Handling
- **repeated_action_limit**: If you receive this observation, it means you are stuck in a loop (e.g., reading the same file offset repeatedly). Stop the current action, analyze the previous output, and proceed with a different step (e.g., writing the fix or reading a different section).
- **Tool Errors**: Distinguish between bad input, timeouts, missing capabilities, or unread outputs. Provide one bounded fallback and stop condition; never prescribe blind repetition.

## Workflow
- Prefer concise always-on guidance. Do not add code for a one-off mistake.
- Use `scripts/<name>.py` for repeated deterministic extraction if needed, but prefer direct tool use for simple tasks.