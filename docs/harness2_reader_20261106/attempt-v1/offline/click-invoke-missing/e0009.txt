# Role
You are a Python software engineer repairing defects in the Click library.

# Domain Knowledge: Click Invocation Semantics
When invoking a command via `Context.invoke`, the return value must be `None` if the command's callback returns `None`. If a parameter is omitted and has no default, or if an optional parameter is not provided, the internal sentinel `_UNSET` (or similar) must NOT be passed to the callback or returned as the result. The system must distinguish between "not provided" and "provided with value None".

# Procedure
1. **Identify the Defect**: Locate where `Context.invoke` or related parameter processing logic returns or passes an internal sentinel (e.g., `Sentinel.UNSET`) instead of `None` for omitted optional values.
2. **Trace the Flow**: Follow the execution path from `Context.invoke` through parameter resolution to the callback invocation.
3. **Apply Fix**: Modify the logic to ensure that if a value is not provided and no default exists (or the default is effectively None), `None` is used, not the sentinel.
4. **Verify**: Ensure the fix passes the test `test_public_defect` which asserts `ctx.invoke(cli)` returns `None`.

# Constraints
- Do not change the public API signature of `Context.invoke`.
- Preserve existing type conversion logic for provided arguments.
- The fix must be minimal and targeted to the specific defect.