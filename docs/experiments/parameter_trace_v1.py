"""Bounded actual parameter/line observations from certified public checks only."""

import json
import shutil

from docs.experiments import runtime_observation_v1 as observer
from evals.process import run_process, test_environment

WATCH = ('salt', 'args', 'prefix', 'prog', 'text_width')
ATTRS = ('salt', 'width', 'current_indent')
TRACE_SETUP = r'''
selection = json.loads(pathlib.Path(sys.argv[5]).read_text(encoding='utf-8'))
active_test, seen, traces, dropped = '', {}, [], 0
code_targets = {}

def safe(value):
    if value is None or type(value) in (bool, int, float): return value
    if type(value) is str: return {'type': 'str', 'value': value[:64], 'truncated': len(value)>64}
    if type(value) is bytes: return {'type': 'bytes', 'hex': value[:64].hex(), 'truncated': len(value)>64}
    return {'type': '<unrecorded>'}

def trace(frame, event, arg):
    global dropped
    if not active_test or event not in ('call', 'line', 'return'): return None
    code = frame.f_code
    if code not in code_targets:
        path = pathlib.Path(code.co_filename).resolve()
        relative = 'src/' + path.relative_to(source).as_posix() if path.is_relative_to(source) else None
        code_targets[code] = next((r for r in selection if r['path']==relative and
                                  r['symbol'].split('.')[-1]==code.co_name and
                                  r['start_line']<=code.co_firstlineno<=r['end_line']), None)
    target = code_targets[code]
    if target is None: return None
    relative = target['path']
    values = {k: safe(frame.f_locals[k]) for k in ('salt','args','prefix','prog','text_width') if k in frame.f_locals}
    obj = frame.f_locals.get('self')
    if obj is not None:
        try: attributes = object.__getattribute__(obj, '__dict__')
        except (AttributeError, TypeError): attributes = {}
        if type(attributes) is dict:
            values.update({'self.'+k: safe(attributes[k]) for k in ('salt','width','current_indent') if k in attributes})
    key = id(frame)
    if event != 'line' or seen.get(key) != values:
        if len(traces)<400:
            traces.append({'test':active_test,'path':relative,'symbol':target['symbol'],
                           'line':frame.f_lineno,'event':event,'values':values})
        else: dropped += 1
    seen[key] = values
    if event=='return': seen.pop(key, None)
    return trace
'''
BOOT = observer.BOOT.replace("source, harness, package, destination = sys.argv[1:]",
                             "source, harness, package, destination = sys.argv[1:5]")
BOOT = BOOT.replace('class Result(unittest.TextTestResult):', TRACE_SETUP + """
class Result(unittest.TextTestResult):
    def startTest(self, test):
        global active_test
        active_test = test.id()
        super().startTest(test)
    def stopTest(self, test):
        global active_test
        active_test = ''
        super().stopTest(test)
""")
BOOT = BOOT.replace('    result = unittest.TextTestRunner', '    sys.settrace(trace)\n    result = unittest.TextTestRunner')
BOOT = BOOT.replace('    for name, module in list(sys.modules.items()):',
                    '    sys.settrace(None)\n    record.update(parameter_trace=traces, trace_dropped=dropped)\n    for name, module in list(sys.modules.items()):')


def capture(workspace, harness, expected_hash, root, python, name, evidence):
    public = observer.public
    repair = public.repair
    repair.validate_evidence(workspace, [r['path'] for r in evidence], evidence)
    if repair.digest(repair.snapshot(harness)) != expected_hash:
        raise ValueError('Public harness changed')
    root.mkdir(parents=True, exist_ok=False)
    source = root/'source'; shutil.copytree(workspace, source)
    before = repair.digest(repair.snapshot(source))
    selection = root/'selection.json'
    selection.write_text(json.dumps([{k:r[k] for k in ('path','symbol','start_line','end_line')}
                                    for r in evidence if r.get('symbol')]), encoding='utf-8')
    destination = root/'observation.json'
    package = 'itsdangerous' if name.startswith('itsdangerous-') else 'click' if name.startswith('click-') else name
    process = run_process([str(python), '-I', '-B', '-c', BOOT, str((source/'src').resolve()),
                           str(harness.resolve()), package, str(destination.resolve()), str(selection.resolve())],
                          source, 15, root/'stdout.txt', root/'stderr.txt', test_environment(source))
    record = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
    category = observer.classify(record, process)
    if category not in ('passed', 'assertion_failure', 'candidate_runtime_error'):
        raise ValueError('Parameter trace public execution failed: '+category)
    if repair.digest(repair.snapshot(source)) != before or repair.digest(repair.snapshot(harness)) != expected_hash:
        raise ValueError('Tracing mutated source or checks')
    return record


def equivalent(left, right):
    keys = ('complete','tests_run','successful','issues','skipped','expected_failures','unexpected_successes')
    return all(left.get(k) == right.get(k) for k in keys)


def pack(record, max_chars):
    failures = {i['test'].split(' (')[0] for i in record.get('issues', [])}
    rows = [r for r in record.get('parameter_trace', []) if any(r['test'].endswith('.'+t) for t in failures)]
    result = {'source':'actual execution of public tests on current candidate; not expected values',
              'line_semantics':'line events precede execution; branch truth is not inferred',
              'events':[], 'omitted_events':len(rows), 'capture_dropped':record.get('trace_dropped',0)}
    for row in rows:
        trial = dict(result, events=result['events']+[row], omitted_events=len(rows)-len(result['events'])-1)
        if len(json.dumps(trial, ensure_ascii=False)) > max_chars: break
        result = trial
    if len(json.dumps(result, ensure_ascii=False)) > max_chars: return None
    return result
