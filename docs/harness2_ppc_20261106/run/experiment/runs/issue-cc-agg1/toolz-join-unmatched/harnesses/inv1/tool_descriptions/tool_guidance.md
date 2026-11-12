When editing Python files, ensure all names used are defined in the current scope. In this workspace, `iteritems` is a Python 2 construct that does not exist in Python 3; use `.items()` instead.

Before submitting a fix, verify that the change resolves the NameError by checking that the function can be called without raising an exception.