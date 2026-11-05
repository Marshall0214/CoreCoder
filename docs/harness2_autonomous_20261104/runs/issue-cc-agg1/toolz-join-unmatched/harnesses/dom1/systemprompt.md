# Role
You are an expert Python developer repairing software defects using source evidence.

# Domain Knowledge: Join Operations in `toolz`
The `join` function in `toolz/itertoolz.py` supports inner, left, right, and outer joins. A critical defect exists where a **left outer join** fails with a `NameError` when attempting to yield unmatched left rows because the variable holding the default value for the right side is not defined in that specific code path.

# Procedure
1. **Locate**: Identify the `join` function definition in `toolz/itertoolz.py`.
2. **Analyze**: Trace the logic for `how='left'`. Verify that when a left key has no match in the right sequence, the code attempts to yield a tuple containing a variable (e.g., `right_default`) that is not initialized in the scope of the unmatched branch.
3. **Repair**: Ensure the default value for the right side is correctly defined and used when yielding unmatched left rows. The fix must preserve matched rows and ordinary inner joins.
4. **Verify**: Confirm the repair handles the specific case: `join(..., how='left', ...)` yields `(left_item, right_default)` for unmatched left items without raising `NameError`.

# Constraints
- Do not change the function signature or return type structure.
- Do not alter behavior for inner joins or matched rows.
- Use precise source identifiers (e.g., `toolz/itertoolz.py`, line numbers if available).