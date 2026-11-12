# TOOL USAGE GUIDANCE

## File Reading Strategy
- Use `read_file` with specific offsets when searching for function definitions
- When a file is large, read in chunks starting from known locations (e.g., after finding a function name via search)
- Always verify the complete function definition before making changes

## Search Operations
- Use `search` with precise query strings to locate function definitions
- Combine search results with targeted reads to understand context
- When searching for patterns like "def style", expect multiple matches and verify the correct one

## Patch Application
- Every edit must have non-empty old text and new text
- Edits must be in array format: [{"file": "path", "old": "...", "new": "..."}]
- Verify the patch schema before submission to avoid validation failures

## Validation Checks
- After applying a fix, verify it passes both Reproduce and Preserve tests
- The Reproduce test checks that the defect is fixed (e.g., palette index 0 works)
- The Preserve test ensures existing functionality remains intact

# DOMAIN-SPECIFIC GUIDANCE FOR CLICK COLOR HANDLING

When working with `click.style()` or `click.secho()`:
1. Check if the color parameter is an integer (palette index) vs string (named color) vs tuple (RGB)
2. For palette indices 0-255, generate ANSI sequence `38;5;<index>` for fg or `48;5;<index>` for bg
3. Validate inputs: raise ValueError for unknown names, booleans, out-of-range indices, malformed RGB
4. Preserve reset behavior (\x1b[0m) and handle color disabled mode correctly
5. Test with edge cases: index 0, index 255, negative indices, non-integer values