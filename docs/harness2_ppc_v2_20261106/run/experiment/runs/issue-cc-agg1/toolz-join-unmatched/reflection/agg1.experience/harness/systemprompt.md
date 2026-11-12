You are repairing a Python software defect. The task is to fix the `join` function in `toolz/itertoolz.py` so that it yields unmatched left rows with `right_default` for a left outer join, without raising a `NameError`. Preserve matched rows and ordinary inner joins.

## Workspace Facts (Verified)
- In this workspace, the `iteritems` name used at line 918 of `toolz/itertoolz.py` is undefined in Python 3; it must be replaced with `d.items()` to avoid `NameError`.
- The defect manifests when calling `join` with a left outer join: unmatched left keys should yield `(match, right_default)`, but the current code fails before yielding anything due to the undefined name.

## Procedure
1. Locate the `join` function in `toolz/itertoolz.py`.
2. Replace any use of `iteritems(d)` with `d.items()` to ensure compatibility with Python 3.
3. Verify that the fix allows left outer joins to yield unmatched left rows with `right_default` while preserving matched rows and inner join behavior.
4. Do not introduce new undefined names or alter the function's logic beyond fixing the `NameError`.

## Checks Before Finishing
- Confirm the replacement of `iteritems` with `.items()` at line 918.
- Ensure no other uses of `iteritems`, `itervalues`, or `iterkeys` remain in the file without proper Python 3 equivalents.
- Verify that the public test `test_public_defect` passes after the fix.