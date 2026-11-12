# Tool Usage Guidance

## read_file
Use `read_file` to inspect source code when you need to understand implementation details. Always specify the correct path and offset if reading large files.

## search
Use `search` to locate specific function definitions or patterns across the codebase. This is efficient for finding where a bug might be located before diving into full file reads.

## read_symbol
Use `read_symbol` when you need precise information about a specific class method or function. If ambiguous, use qualified symbols (e.g., `ClassName.method_name`).

## apply_patch
When proposing fixes, ensure your patch follows the required schema: an array of edits with `file`, `old`, and `new` fields. The `old` text must match exactly once in the source file.

# Common Pitfalls
- **Invalid Patch Schema**: Ensure every edit has a non-empty `old` string that appears exactly once in the target file.
- **Ambiguous Symbols**: When using `read_symbol`, prefer fully qualified names to avoid ambiguity errors.
- **Repeated Actions**: Avoid re-reading the same file section multiple times; use offsets or search results to navigate efficiently.