"""Isolated public-test trace of locate/replace inputs and their predicate arguments."""
import collections
import collections.abc
import importlib
import json
import pathlib
import sys
import types
import unittest


def value(item, depth=0):
    # Never invoke user-defined repr, iteration or equality to serialize an object.
    if type(item) in (bool, int, float, type(None)):
        return item
    if type(item) is str:
        return item[:80]
    if type(item) in (list, tuple) and depth < 2:
        return {'type': type(item).__name__, 'items': [value(x, depth + 1) for x in item[:12]],
                'omitted': max(0, len(item) - 12)}
    return {'type': type(item).__name__, 'value': 'not captured'}


def run(workspace, source_root, harness, package, allowed, group, destination):
    source = (pathlib.Path(workspace) / source_root).resolve()
    allowed = {(pathlib.Path(workspace) / p).resolve() for p in allowed}
    public_file = (pathlib.Path(harness) / 'test_admission.py').resolve()
    for name in ('Mapping', 'MutableMapping', 'Sequence', 'MutableSequence', 'Set', 'MutableSet',
                 'Iterable', 'Iterator', 'Callable', 'Container', 'Hashable', 'ItemsView', 'KeysView', 'ValuesView'):
        if not hasattr(collections, name):
            setattr(collections, name, getattr(collections.abc, name))
    sys.path.insert(0, str(source))
    module = importlib.import_module(package)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Package shadowed source'
    discovered = unittest.defaultTestLoader.discover(str(harness), pattern='test_admission.py')
    if unittest.defaultTestLoader.errors:
        raise RuntimeError('Discovery failed')
    selected = unittest.TestSuite()

    def select(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                select(item)
            elif item.__class__.__name__ == group:
                selected.addTest(item)
    select(discovered)
    records = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            self.record = {'test': test.id(), 'passed': True, 'truncated': False, 'operations': []}
            self.callbacks, self.active, self.frames = {}, {}, {}
            sys.settrace(self.trace)

        def trace(self, frame, event, arg):
            code = frame.f_code
            if (event == 'call' and code.co_name in ('locate', 'replace')
                    and pathlib.Path(code.co_filename).resolve() in allowed):
                if id(frame) not in self.frames:
                    if len(self.record['operations']) >= 12:
                        self.record['truncated'] = True
                        return self.trace
                    self.frames[id(frame)] = frame
                    row = {'function': code.co_name, 'line': frame.f_lineno,
                           'input': value(frame.f_locals.get('iterable')),
                           'window_size': value(frame.f_locals.get('window_size')), 'predicate_calls': []}
                    self.record['operations'].append(row)
                    pred = frame.f_locals.get('pred')
                    if type(pred) is types.FunctionType and pathlib.Path(pred.__code__.co_filename).resolve() == public_file:
                        self.callbacks[pred.__code__] = row
                # Keep generator frames alive to prevent id reuse; never serialize their other locals.
                return self.trace
            if code not in self.callbacks:
                return self.trace
            operation = self.callbacks[code]
            if event == 'call':
                if len(operation['predicate_calls']) >= 16:
                    self.record['truncated'] = True
                    return self.trace
                count = code.co_argcount
                args = [frame.f_locals.get(name) for name in code.co_varnames[:count]]
                if code.co_flags & 4:
                    args.extend(frame.f_locals.get(code.co_varnames[count + code.co_kwonlyargcount], ()))
                call = {'arguments': value(tuple(args)), 'line': frame.f_lineno}
                operation['predicate_calls'].append(call)
                self.active[id(frame)] = call
            elif id(frame) in self.active:
                if event == 'exception':
                    self.active[id(frame)]['exception_type'] = arg[0].__name__
                elif event == 'return':
                    self.active.pop(id(frame))['return'] = value(arg)
            return self.trace

        def addFailure(self, test, err):
            self.record['passed'] = False
            super().addFailure(test, err)

        def addError(self, test, err):
            self.record['passed'] = False
            super().addError(test, err)

        def addSubTest(self, test, subtest, err):
            if err:
                self.record['passed'] = False
            super().addSubTest(test, subtest, err)

        def stopTest(self, test):
            sys.settrace(None)
            records.append(self.record)
            super().stopTest(test)

    try:
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(selected)
    finally:
        sys.settrace(None)
    for name, module in list(sys.modules.items()):
        if (name == package or name.startswith(package + '.')) and getattr(module, '__file__', None):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Submodule shadowed source'
    output = {'tests_run': result.testsRun, 'successful': result.wasSuccessful(), 'records': records,
              'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
              'unexpected_successes': len(result.unexpectedSuccesses)}
    pathlib.Path(destination).write_text(json.dumps(output), encoding='utf-8')


if __name__ == '__main__':
    workspace, source_root, harness, package, allowed, group, destination = sys.argv[1:]
    run(workspace, source_root, harness, package, json.loads(allowed), group, destination)
