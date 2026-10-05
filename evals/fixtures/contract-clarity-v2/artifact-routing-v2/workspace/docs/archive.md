# Archive contract

archive_plan maps original input path strings to destinations.
Matching logical repository paths is case-sensitive. Backslash and slash are equivalent separators;
repeated separators and single-dot (`.`) segments are removed in both input paths and rule patterns.
These are logical repository strings, not filesystem paths: a double-dot (`..`) segment stays literal
and never traverses a parent directory. For example `./a//b.txt` becomes `a/b.txt`, while
`a/../a/b.txt` remains `a/../a/b.txt` and does not match the literal pattern `a/./b.txt`.
Rule patterns use fnmatchcase semantics after this normalization.
Choose the matching rule with highest priority; preserve input rule order for equal priorities.
No match maps to unassigned. Do not reorder or mutate rules or input paths.
preview_first intentionally reflects the first raw matching rule for configuration debugging.
Notification channels likewise preserve configured order.
