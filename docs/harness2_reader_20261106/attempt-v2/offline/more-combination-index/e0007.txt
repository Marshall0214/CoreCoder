# Tool Usage Guidance

## Reading Source Code
- Use `read_symbol` to retrieve full function definitions when available. This ensures you have the complete context of the logic being modified.
- Use `search` to locate all occurrences of a function name, including test cases that define expected behavior.

## Applying Patches
- When using `apply_patch`, ensure the `old` string matches the source exactly (including whitespace and indentation).
- The `new` string must implement the fix while preserving the original docstring and structure unless explicitly required to change.

## Validation Logic
- For functions involving combinatorial logic (e.g., `combination_with_replacement_index`):
  - **Input Validation**: Explicitly check that every element in the input tuple exists in the pool. Raise `ValueError` if not.
  - **Order Validation**: Ensure the input elements are in non-decreasing order relative to their indices in the pool. Raise `ValueError` if the sequence is decreasing.
  - **Edge Cases**: Handle empty inputs (`l == 0`) by returning `0` immediately, as per standard combinatorial definitions.

## Evidence-Based Reasoning
- Do not assume test outcomes. Cite specific lines from `tests/test_more.py` or the function definition in `more_itertools/more.py` to justify changes.
- If a trajectory shows a failure (e.g., missing validation), encode that specific check into the guidance.