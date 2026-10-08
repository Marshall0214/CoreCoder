"""Versioned public assertion observations; no candidate-computed oracle.

Reproduce equality expectations come from public tests; Preserve equality actuals
come from healthy original behavior. This strengthens existing cases, not coverage.
"""
import ast
import json

# Embedded into isolated stdlib-only harnesses; no evals import in model-facing tests.
SUPPORT = '''
import json as _cc_json
from pathlib import Path as _cc_Path

def _cc_encode(value, depth=0):
    if depth > 20:
        raise ValueError('Snapshot nesting exceeds limit')
    kind = type(value)
    if kind in (type(None), bool, int, str):
        if len(str(value)) > 100000:
            raise ValueError('Snapshot scalar exceeds limit')
        return [kind.__name__, value]
    if kind is float:
        return ['float', value.hex()]
    if kind is bytes:
        if len(value) > 100000:
            raise ValueError('Snapshot bytes exceeds limit')
        return ['bytes', value.hex()]
    if kind in (list, tuple, set, frozenset, dict):
        if len(value) > 10000:
            raise ValueError('Snapshot container exceeds limit')
        if kind is dict:
            items = [[_cc_encode(k, depth+1), _cc_encode(v, depth+1)] for k,v in value.items()]
        else:
            items = [_cc_encode(v, depth+1) for v in value]
        if kind in (dict, set, frozenset):
            items.sort(key=lambda item: _cc_json.dumps(item, sort_keys=True))
        return [kind.__name__, items]
    raise ValueError('Unsupported snapshot value: ' + kind.__name__)

def _cc_decode(encoded):
    kind, value = encoded
    if kind in ('NoneType', 'bool', 'int', 'str'):
        return value
    if kind == 'float':
        return float.fromhex(value)
    if kind == 'bytes':
        return bytes.fromhex(value)
    if kind == 'dict':
        return {_cc_decode(k): _cc_decode(v) for k,v in value}
    values = [_cc_decode(v) for v in value]
    return {'list':list, 'tuple':tuple, 'set':set, 'frozenset':frozenset}[kind](values)

def _cc_record(key, encoded):
    path = _cc_Path(_cc_output)
    data = _cc_json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    data.setdefault(key, []).append(encoded)
    path.write_text(_cc_json.dumps(data, sort_keys=True), encoding='utf-8')
'''

METHODS = '''
def _cc_take(self, site):
    key = site + '|' + self._testMethodName
    if not hasattr(self, '_cc_seen'):
        self._cc_seen = {}
    index = self._cc_seen.get(key, 0)
    self._cc_seen[key] = index + 1
    if key not in _cc_expected or index >= len(_cc_expected[key]):
        self.fail('Unexpected frozen assertion observation: ' + key)
    return _cc_expected[key][index]

def _cc_actual(self, site, actual):
    encoded = _cc_encode(actual)
    if _cc_mode == 'record':
        _cc_record(site + '|' + self._testMethodName, encoded)
    else:
        self.assertEqual(encoded, self._cc_take(site), 'Original normal behavior changed: ' + site)
    return actual

def _cc_expect(self, site, value=None):
    if _cc_mode == 'record':
        _cc_record(site + '|' + self._testMethodName, _cc_encode(value))
        return value
    return _cc_decode(self._cc_take(site))

def tearDown(self):
    if _cc_mode == 'verify':
        prefix = self.__class__.__name__ + '@'
        suffix = '|' + self._testMethodName
        for key, values in _cc_expected.items():
            if key.startswith(prefix) and key.endswith(suffix):
                self.assertEqual(getattr(self, '_cc_seen', {}).get(key, 0), len(values),
                                 'Frozen assertion observation missing: ' + key)
'''

EQUALITY = {'assertEqual', 'assertListEqual', 'assertTupleEqual', 'assertDictEqual', 'assertSetEqual',
            'assertSequenceEqual', 'assertMultiLineEqual'}


def render(code, *, mode, observations=None, output=None):
    """Instrument only explicit Reproduce/Preserve equality assertions.

    Record Reproduce expected expressions without invoking defective actual calls.
    Candidate verification reads frozen expectations, not the candidate's version
    of the expected expression. Existing other assertions remain in place.
    """
    if mode not in {'record', 'verify'} or (mode == 'record' and not output):
        raise ValueError('Invalid snapshot mode/output')
    if observations is not None and not isinstance(observations, dict):
        raise ValueError('Expected observation mapping')
    tree = ast.parse(code)
    if any(isinstance(node, ast.Name) and node.id.startswith('_cc_') for node in ast.walk(tree)):
        raise ValueError('Reserved frozen-assertion name')
    groups = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in {'Reproduce', 'Preserve'}]
    if {node.name for node in groups} != {'Reproduce', 'Preserve'} or len(groups) != 2:
        raise ValueError('Require unique public check groups')
    count = 0
    for group in groups:
        if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
               (node.name == 'tearDown' or node.name.startswith('_cc_')) for node in group.body):
            raise ValueError('Existing teardown or reserved method is unsupported')

        class Instrument(ast.NodeTransformer):
            def __init__(self, group_name):
                self.group_name = group_name

            def visit_Call(self, node):
                nonlocal count
                if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'self' and node.func.attr in EQUALITY and len(node.args) >= 2):
                    if self.group_name == 'Reproduce':
                        try:
                            ast.literal_eval(node.args[1])
                        except (ValueError, TypeError):
                            pass
                        else:
                            # Literal expectations are already immutable; keep exception/setup semantics.
                            return self.generic_visit(node)
                    site = f'{self.group_name}@{node.lineno}:{node.col_offset}'
                    count += 1
                    helper = '_cc_expect' if self.group_name == 'Reproduce' else '_cc_actual'
                    arg = node.args[1] if self.group_name == 'Reproduce' else node.args[0]
                    args = [ast.Constant(site)]
                    if mode == 'record' or self.group_name == 'Preserve':
                        args.append(arg)
                    probe = ast.Call(ast.Attribute(ast.Name('self', ast.Load()), helper, ast.Load()), args, [])
                    if mode == 'record' and self.group_name == 'Reproduce':
                        return ast.copy_location(probe, node)
                    node.args[1 if self.group_name == 'Reproduce' else 0] = probe
                    return node
                return self.generic_visit(node)

        # Do not instrument generated helpers, nested classes or teardown behavior.
        for method in group.body:
            if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                Instrument(group.name).visit(method)
        group.body.extend(ast.parse(METHODS).body)
    if not count:
        raise ValueError('No supported equality assertions')
    constants = (f'_cc_mode = {mode!r}\n_cc_output = {str(output)!r}\n'
                 f'_cc_expected = {observations or {}!r}\n')
    # Prefix after future imports to keep valid Python semantics.
    prefix = 0
    while prefix < len(tree.body) and (isinstance(tree.body[prefix], ast.Expr) and
                                      isinstance(tree.body[prefix].value, ast.Constant) and
                                      isinstance(tree.body[prefix].value.value, str)
                                      or isinstance(tree.body[prefix], ast.ImportFrom) and
                                      tree.body[prefix].module == '__future__'):
        prefix += 1
    tree.body[prefix:prefix] = ast.parse(constants + SUPPORT).body
    source = ast.unparse(ast.fix_missing_locations(tree)) + '\n'
    compile(source, '<frozen-public-checks>', 'exec')
    return source, {'assertion_sites': count, 'mode': mode,
                    'observation_calls': sum(len(values) for values in (observations or {}).values())}


def observation_hash(observations):
    import hashlib
    return hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest()
