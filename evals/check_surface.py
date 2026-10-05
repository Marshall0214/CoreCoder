"""Conservative caller-state assertion filter, not a semantic correctness proof."""

import ast

PROTOCOL = "public-contract-feedback-v5-surface"
GENERATION_RULES = (
    ' Use only unittest and the supplied repository modules, including for helper objects. '
    'If a fixture needs an attribute-bearing object, define a small plain Python class with __init__; '
    'do not import dataclasses, types or other standard-library helpers. '
    'Check API return values and observable behavior across repeated calls. Do not inspect caller-owned '
    'arguments after passing them to repository APIs, including sets, caches and their aliases. '
    'Do not assume the internal representation of event identities or bookkeeping state.'
)


def names(node):
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def caller_state_tests(code):
    """Reject whole methods inspecting input names or aliases; no partial test rewriting.

    This intentionally excludes even documented input mutation. It is a syntactic
    restriction on simple generated tests, not general Python alias analysis.
    """
    tree = ast.parse(code)
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module != 'unittest':
            imported |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            imported |= {alias.asname or alias.name.split('.')[0] for alias in node.names if alias.name != 'unittest'}
    rejected = {}
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef) or not method.name.startswith('test_'):
                continue
            inputs = set()
            assertions = []
            assignments = []
            for node in ast.walk(method):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    assignments.append(node)
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self':
                    if node.func.attr.startswith('assert'):
                        assertions.append(node)
                    continue
                if not names(node.func) & imported:
                    continue
                for arg in [*node.args, *(item.value for item in node.keywords)]:
                    inputs |= names(arg)
            changed = True
            while changed:
                changed = False
                for assignment in assignments:
                    value = assignment.value
                    # An API result gets its own observable name, even if the API
                    # returns an input object. Other derived aliases stay tainted.
                    if value is None or isinstance(value, ast.Call) or not names(value) & inputs:
                        continue
                    targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                    added = set().union(*(names(target) for target in targets)) - inputs
                    inputs |= added
                    changed |= bool(added)
            observed = set().union(*(names(arg) for call in assertions
                                     for arg in [*call.args, *(item.value for item in call.keywords)]))
            if observed & inputs:
                rejected[f'{cls.name}.{method.name}'] = sorted(observed & inputs)
    return rejected


def filter_surface_checks(code, reviews):
    if code is None:
        return None, {}
    rejected = caller_state_tests(code)
    for row in reviews:
        if row['verdict'] == 'accept' and row['test'] in rejected:
            row.update(model_verdict='accept', verdict='reject',
                       surface_error='Caller-owned argument or alias observed',
                       observed_input_names=rejected[row['test']])
    accepted = {row['test'] for row in reviews if row['verdict'] == 'accept'}
    tree = ast.parse(code)
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            cls.body = [node for node in cls.body if not (
                isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                and f'{cls.name}.{node.name}' not in accepted)] or [ast.Pass()]
    return (ast.unparse(tree) + '\n' if accepted else None), rejected
