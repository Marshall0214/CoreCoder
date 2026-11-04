# Tool Guidance for Python Defect Repair

## Analytic Moves
- **Trace**: Follow the execution path of the `join` function in `toolz/itertoolz.py`. Identify where the iterator logic diverges for left outer joins.
- **Reconcile**: Compare the current implementation against the requirement: "yield unmatched left rows with right_default". Identify missing checks or variable scopes.
- **Draft**: Propose a code change that introduces the necessary check for `right_default` and ensures it is used when the right sequence is exhausted or no match is found.

## Artifact Contract
- **Required Parts**: The repaired `join` function must include logic to handle the `how='left'` case explicitly.
- **Dependencies**: The fix depends on the correct handling of iterators (`seq1`, `seq2`) and the `right_default` parameter.
- **Domain Checks**: 
  - Verify that no `NameError` occurs when accessing variables related to the right sequence in unmatched cases.
  - Ensure matched rows are still yielded correctly.
  - Confirm inner joins (default behavior) remain unchanged.

## Decision Rules
- **Trigger**: The presence of a `NameError` or missing unmatched rows in a left outer join test case.
- **Supporting Evidence**: The trajectory shows the agent reading `toolz/itertoolz.py` but failing to locate the specific logic gap for `right_default` in the `join` function (Step 4-7 show repeated reads of the same offset without finding the `join` definition at line 813).
- **Conflicts**: Balancing the need to add new logic for left joins without breaking existing inner join behavior.
- **Uncertainty**: Explicitly state if the exact location of the `right_default` usage is ambiguous in the current code view, requiring a full read of the function.

## Workspace Facts (Verified)
- In this workspace, the `join` function is defined at line 813 in `toolz/itertoolz.py`.
- The agent's trajectory (Steps 4-7) shows repeated attempts to read `toolz/itertoolz.py` starting at offset 800, which returns content from functions like `accumulate`, `groupby`, and `merge_sorted`, failing to reach the `join` function definition. This indicates a need for precise navigation or a full file read to locate the defect.
- The defect is specifically that `join` does not yield unmatched left rows with `right_default` for a left outer join, likely due to missing logic or a `NameError` when accessing right-side data for unmatched keys.