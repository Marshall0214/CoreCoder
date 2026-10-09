"""Isolated public-only numeric observations and prompt call arguments; no repair code."""
import ast
import collections
import collections.abc
import importlib
import json
import math
import pathlib
import sys
import unittest


def primitive(value):
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is str:
        return value[:120]
    return {'type': type(value).__name__, 'captured': False}


def run(job, destination):
    workspace = pathlib.Path(job['workspace']).resolve()
    source = (workspace / job['source_root']).resolve()
    if not source.is_relative_to(workspace):
        raise ValueError('Source escapes workspace')
    for name in ('Mapping', 'MutableMapping', 'Sequence', 'MutableSequence', 'Set', 'MutableSet',
                 'Iterable', 'Iterator', 'Callable', 'Container', 'Hashable'):
        if not hasattr(collections, name):
            setattr(collections, name, getattr(collections.abc, name))
    sys.path.insert(0, str(source))
    module = importlib.import_module(job['package'])
    if not pathlib.Path(module.__file__).resolve().is_relative_to(source):
        raise ValueError('Installed package shadowed source')
    harness = pathlib.Path(job['harness']).resolve()
    discovered = unittest.defaultTestLoader.discover(str(harness), pattern='test_admission.py')
    if unittest.defaultTestLoader.errors:
        raise ValueError('Public discovery failed')
    suite = unittest.TestSuite()

    def select(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                select(item)
            elif item.__class__.__name__ in ('Reproduce', 'Preserve'):
                suite.addTest(item)

    select(discovered)
    allowed = {(workspace / name).resolve() for name in job['allowed_files']}
    calls = []
    omitted = 0

    def trace(frame, event, _arg):
        nonlocal omitted
        if event == 'call' and frame.f_code.co_name in ('prompt_func', 'visible_input', 'hidden_input', '_build_prompt'):
            path = pathlib.Path(frame.f_code.co_filename).resolve()
            if path in allowed:
                fields = {name: primitive(frame.f_locals[name]) for name in ('text', 'prompt', 'suffix')
                          if name in frame.f_locals}
                if len(calls) >= 12:
                    omitted += 1
                else:
                    calls.append({'path': path.relative_to(workspace).as_posix(),
                                  'line': frame.f_code.co_firstlineno, 'function': frame.f_code.co_name, 'arguments': fields})
        return trace

    try:
        sys.settrace(trace)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        sys.settrace(None)
    numeric = []
    tree = ast.parse((harness / 'test_admission.py').read_text(encoding='utf-8'))
    # Reuse only literal constructor inputs that already occur in public checks.
    public_nodes = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
                    and cls.name in ('Reproduce', 'Preserve') for node in ast.walk(cls)]
    for node in public_nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'numeric_range':
            continue
        if node.keywords or not 1 <= len(node.args) <= 3 or len(numeric) >= 4:
            continue
        try:
            args = [ast.literal_eval(arg) for arg in node.args]
        except (ValueError, TypeError):
            continue
        if any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 100 for x in args):
            continue
        rng = module.numeric_range(*args)
        values = []
        iterator = iter(rng)
        for _ in range(13):
            try:
                values.append(next(iterator))
            except StopIteration:
                break
        if len(values) > 12:
            numeric.append({'arguments': args, 'truncated': True})
            continue
        rows = []
        for value in values:
            row = {'value': primitive(value), 'contains': value in rng}
            try:
                row['index'] = rng.index(value)
            except Exception as exc:  # noqa: BLE001 - observe exception type only
                row['index_exception'] = type(exc).__name__
            rows.append(row)
        numeric.append({'arguments': args, 'truncated': False, 'length': len(rng), 'iteration': rows})
    for name, loaded in list(sys.modules.items()):
        if ((name == job['package'] or name.startswith(job['package'] + '.')) and getattr(loaded, '__file__', None)
                and not pathlib.Path(loaded.__file__).resolve().is_relative_to(source)):
            raise ValueError('Submodule shadowed source')
    record = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
              'unexpected_successes': len(result.unexpectedSuccesses), 'successful': result.wasSuccessful(),
              'prompt_calls': calls, 'omitted_prompt_calls': omitted, 'numeric': numeric}
    pathlib.Path(destination).write_text(json.dumps(record), encoding='utf-8')


if __name__ == '__main__':
    job_path, destination_path = sys.argv[1:]
    run(json.loads(pathlib.Path(job_path).read_text(encoding='utf-8')), destination_path)
