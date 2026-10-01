# Archive contract

archive_plan maps original input path strings to destinations.
Matching logical repository paths is case-sensitive. Backslash and slash are equivalent separators;
repeated separators and dot segments are normalized. Rule patterns use fnmatchcase semantics.
Choose the matching rule with highest priority; preserve input rule order for equal priorities.
No match maps to unassigned. Do not reorder or mutate rules or input paths.
preview_first intentionally reflects the first raw matching rule for configuration debugging.
Notification channels likewise preserve configured order.
