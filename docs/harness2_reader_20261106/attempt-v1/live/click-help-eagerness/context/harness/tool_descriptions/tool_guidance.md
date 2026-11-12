Tool Usage Guidance

read_file:
- Use precise offsets to read specific sections of files.
- Avoid reading entire large files unless necessary; prefer targeted reads.
- After a patch failure, re-read the affected region to verify current state.

read_symbol:
- Use this to locate function or class definitions before editing.
- Helps ensure you are modifying the correct code block.

apply_patch:
- Patches must follow the exact schema: {"edits": [{"path": "...", "old_text": "...", "new_text": "..."}]}
- The 'old_text' must match exactly one occurrence in the file.
- If patch fails with 'invalid_patch_schema', check that your JSON structure is correct.
- If patch fails with 'anchor_not_found', re-read the file section to confirm content before retrying.

search:
- Use to find occurrences of patterns when unsure of exact location.
- Helps identify where to read or edit.