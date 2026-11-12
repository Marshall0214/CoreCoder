You are repairing a Python software defect. The task is to fix the `join` function in `toolz/itertoolz.py` so that it yields unmatched left rows with `right_default` for a left outer join, without raising a NameError.

In this workspace, the defect is at line 918 of `toolz/itertoolz.py`: the code uses `iteritems(d)` which is undefined in Python 3. The fix is to replace `iteritems(d)` with `d.items()`.

Preserve matched rows and ordinary inner joins behavior. Do not change the deliverable shape; only fix the NameError so the function runs correctly.