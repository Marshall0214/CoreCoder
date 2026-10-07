"""Structured public-test observations; attribute only direct candidate tracebacks."""

import json
import shutil

from docs.experiments import repair_public_checks_v1 as public
from evals.process import run_process, test_environment

BOOT = r'''
import importlib, json, pathlib, sys, unittest
source, harness, package, destination = sys.argv[1:]
source, harness = pathlib.Path(source).resolve(), pathlib.Path(harness).resolve()
record = {'version': 1, 'complete': False, 'phase': 'setup', 'tests_run': 0, 'issues': []}
def location(filename):
    path = pathlib.Path(filename).resolve()
    if path.is_relative_to(source): return 'candidate', path.relative_to(source).as_posix()
    if path.is_relative_to(harness): return 'harness', path.relative_to(harness).as_posix()
    return 'unknown', '<external>'
def issue(test, err, assertion=False):
    frames, tb = [], err[2]
    while tb:
        origin, path = location(tb.tb_frame.f_code.co_filename)
        frames.append({'origin': origin, 'path': path, 'line': tb.tb_lineno, 'function': tb.tb_frame.f_code.co_name})
        tb = tb.tb_next
    origin = 'assertion' if assertion else frames[-1]['origin'] if frames else 'unknown'
    return {'test': str(test), 'kind': 'assertion' if assertion else 'exception', 'origin': origin,
            'exception_type': err[0].__name__, 'message': str(err[1])[:500], 'frames': frames[-8:]}
class Result(unittest.TextTestResult):
    def addFailure(self, test, err):
        record['issues'].append(issue(test, err, True)); super().addFailure(test, err)
    def addError(self, test, err):
        record['issues'].append(issue(test, err)); super().addError(test, err)
    def addSubTest(self, test, subtest, err):
        if err is not None: record['issues'].append(issue(subtest, err, issubclass(err[0], test.failureException)))
        super().addSubTest(test, subtest, err)
try:
    sys.path.insert(0, str(source))
    module = importlib.import_module(package)
    assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Installed package shadowed source'
    suite = unittest.defaultTestLoader.discover(str(harness), pattern='test_admission.py')
    if unittest.defaultTestLoader.errors: raise RuntimeError('Public check discovery failed')
    selected = unittest.TestSuite()
    def select(items):
        for item in items:
            if isinstance(item, unittest.TestSuite): select(item)
            elif item.__class__.__name__ == 'PublicContract': selected.addTest(item)
    select(suite)
    record['phase'] = 'execution'
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(selected)
    for name, module in list(sys.modules.items()):
        if name == package or name.startswith(package+'.'):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Submodule shadowed source'
    record.update(complete=True, tests_run=result.testsRun, skipped=len(result.skipped),
                  expected_failures=len(result.expectedFailures), unexpected_successes=len(result.unexpectedSuccesses),
                  successful=result.wasSuccessful())
except Exception as exc:
    record.update(complete=False, infrastructure_exception=type(exc).__name__)
pathlib.Path(destination).write_text(json.dumps(record), encoding='utf-8')
sys.exit(0 if record.get('successful') and record['tests_run'] else 1)
'''


def classify(record, process):
    if process['timed_out']:
        return 'timeout'
    if not isinstance(record, dict) or record.get('version') != 1 or record.get('complete') is not True:
        return 'observer_failure'
    if (type(record.get('tests_run')) is not int or not isinstance(record.get('issues'), list)
            or any(not isinstance(i, dict) for i in record['issues'])):
        return 'observer_failure'
    if record.get('phase') != 'execution' or record.get('tests_run', 0) <= 0:
        return 'no_tests'
    if record.get('skipped') or record.get('expected_failures') or record.get('unexpected_successes'):
        return 'inconclusive_tests'
    issues = record.get('issues', [])
    if record.get('successful'):
        return 'passed' if process['returncode'] == 0 and not issues else 'inconsistent_result'
    if process['returncode'] != 1 or not issues:
        return 'inconsistent_result'
    if any(i.get('origin') not in {'assertion', 'candidate'} for i in issues):
        return 'harness_or_unknown_error'
    return 'candidate_runtime_error' if any(i['origin'] == 'candidate' for i in issues) else 'assertion_failure'


def check_public(workspace, harness, expected_hash, root, python, name):
    """Isolated interpreter, clean source copy and immutable public checks; no private grader."""
    if public.repair.digest(public.repair.snapshot(harness)) != expected_hash:
        raise ValueError('Public harness changed')
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'source'
    shutil.copytree(workspace, source)
    before = public.repair.digest(public.repair.snapshot(source))
    report = root / 'observation.json'
    package = 'itsdangerous' if name.startswith('itsdangerous-') else 'click' if name.startswith('click-') else name
    process = run_process([str(python), '-I', '-B', '-c', BOOT, str((source/'src').resolve()),
                           str(harness.resolve()), package, str(report.resolve())], source, 15,
                          root/'stdout.txt', root/'stderr.txt', test_environment(source))
    try:
        record = json.loads(report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        record = None
    category = classify(record, process)
    if (public.repair.digest(public.repair.snapshot(source)) != before
            or public.repair.digest(public.repair.snapshot(harness)) != expected_hash):
        raise ValueError('Public execution mutated source or checks')
    record = record or {}
    outcome = dict(process, tests_run=record.get('tests_run', 0), passed=category=='passed',
                   assertion_failure=any(i.get('kind')=='assertion' for i in record.get('issues', [])),
                   execution_error=any(i.get('kind')=='exception' for i in record.get('issues', [])),
                   classification=category, observation=record, stderr='stderr.txt', stdout='stdout.txt')
    output = (root/'stderr.txt').read_text(encoding='utf-8', errors='replace')
    return outcome, output.replace(str(source), '<PUBLIC_WORKSPACE>').replace(str(harness), '<PUBLIC_CHECKS>')[-6000:]


def recoverable(outcome):
    return outcome.get('classification') in {'assertion_failure', 'candidate_runtime_error'}
