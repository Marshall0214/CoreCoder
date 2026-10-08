"""Isolated stdlib-only public-test call coverage; never captures local values."""
import collections
import collections.abc
import importlib
import json
import os
import pathlib
import sys
import unittest


def run(workspace, source_root, harness, package, group, allowed, destination):
    workspace = pathlib.Path(workspace).resolve()
    source = (workspace / source_root).resolve()
    paths = {}
    for name in allowed:
        path = (workspace / name).resolve()
        if not path.is_relative_to(workspace) or path.is_symlink():
            raise ValueError('Trace source escapes workspace')
        paths[os.path.normcase(str(path))] = name
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
    cache = {}

    def location(frame):
        code = frame.f_code
        if code not in cache:
            path = paths.get(os.path.normcase(os.path.abspath(code.co_filename)))
            cache[code] = (path, code.co_firstlineno, code.co_name) if path and not code.co_name.startswith('<') else None
        return cache[code]

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            super().startTest(test)
            self.record = {'test': test.id(), 'passed': True, 'truncated': False, 'functions': {}, 'edges': set()}
            self.events = 0
            sys.settrace(self.trace)

        def trace(self, frame, event, arg):
            key = location(frame)
            if key is None:
                return self.trace
            self.events += 1
            info = self.record
            if self.events > 20000 or (key not in info['functions'] and len(info['functions']) >= 256):
                info['truncated'] = True
                return self.trace
            row = info['functions'].setdefault(key, {'path': key[0], 'line': key[1], 'name': key[2],
                                                      'lines': set(), 'exception_lines': set()})
            if event in {'line', 'exception'}:
                field = 'exception_lines' if event == 'exception' else 'lines'
                if len(row[field]) < 128:
                    row[field].add(frame.f_lineno)
                else:
                    info['truncated'] = True
            if event == 'call' and len(info['edges']) < 512:
                parent = frame.f_back
                for _ in range(64):
                    if parent is None:
                        break
                    caller = location(parent)
                    if caller:
                        info['edges'].add((caller, key))
                        break
                    parent = parent.f_back
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
            info = self.record
            info['functions'] = [dict(r, lines=sorted(r['lines']), exception_lines=sorted(r['exception_lines']))
                                 for r in info['functions'].values()]
            info['edges'] = sorted(info['edges'])
            records.append(info)
            super().stopTest(test)

    try:
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(selected)
    finally:
        sys.settrace(None)
    for name, module in list(sys.modules.items()):
        if (name == package or name.startswith(package + '.')) and getattr(module, '__file__', None):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Submodule shadowed source'
    output = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
              'unexpected_successes': len(result.unexpectedSuccesses), 'successful': result.wasSuccessful(),
              'records': records}
    pathlib.Path(destination).write_text(json.dumps(output), encoding='utf-8')


if __name__ == '__main__':
    workspace, source_root, harness, package, group, allowed, destination = sys.argv[1:]
    run(workspace, source_root, harness, package, group, json.loads(allowed), destination)
