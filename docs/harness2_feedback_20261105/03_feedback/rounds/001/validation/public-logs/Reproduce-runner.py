import signal
signal.alarm(15)

import collections, collections.abc, importlib, json, pathlib, sys, unittest
source, checks, package, group, destination = sys.argv[1:]
source = pathlib.Path(source).resolve()
# Identical historical-library compatibility in before, reference and candidate.
for name in ('Mapping','MutableMapping','Sequence','MutableSequence','Set','MutableSet','Iterable','Iterator','Callable','Container','Hashable','ItemsView','KeysView','ValuesView'):
    if not hasattr(collections,name): setattr(collections,name,getattr(collections.abc,name))
sys.path.insert(0,str(source))
module = importlib.import_module(package)
assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Installed package shadowed source'
suite = unittest.defaultTestLoader.discover(checks, pattern='test_admission.py')
if unittest.defaultTestLoader.errors: raise RuntimeError('Discovery failed')
selected = unittest.TestSuite()
def select(items):
    for item in items:
        if isinstance(item,unittest.TestSuite): select(item)
        elif item.__class__.__name__==group: selected.addTest(item)
select(suite)
result=unittest.TextTestRunner(verbosity=2).run(selected)
record={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'expected_failures':len(result.expectedFailures),
        'unexpected_successes':len(result.unexpectedSuccesses),'successful':result.wasSuccessful()}
for name,module in list(sys.modules.items()):
    if name==package or name.startswith(package+'.'):
        if getattr(module,'__file__',None):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Submodule shadowed source'
pathlib.Path(destination).write_text(json.dumps(record),encoding='utf-8')
sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)
