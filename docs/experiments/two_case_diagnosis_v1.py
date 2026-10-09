"""Human hypothesis checks in isolated copies; outputs are never model inputs."""
import argparse
import ast
import shutil
import sys
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import function_replace_v1 as functions
from docs.experiments import system_comparison_v1 as baseline
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

TASKS = ('more-range-membership', 'click-prompt-suffix')
METHODS = {
    'numeric_range.__contains__': '''    def __contains__(self, elem):
        try:
            self.index(elem)
        except ValueError:
            return False
        return True
''',
    'numeric_range.index': '''    def index(self, value):
        inside = self._start <= value < self._stop if self._growing else self._start >= value > self._stop
        if inside:
            q, _ = divmod(value - self._start, self._step)
            for candidate in (int(q) - 1, int(q), int(q) + 1):
                if candidate >= 0 and self._start + candidate * self._step == value:
                    return candidate
        raise ValueError(f"{value} is not in numeric range")
''',
    'numeric_range._len': '''    def _len(self):
        distance = self._stop - self._start if self._growing else self._start - self._stop
        step = self._step if self._growing else -self._step
        if distance <= self._zero:
            return 0
        q, _ = divmod(distance, step)
        size = int(q)
        def inside(i):
            value = self._start + i * self._step
            return value < self._stop if self._growing else value > self._stop
        while inside(size):
            size += 1
        while size > 0 and not inside(size - 1):
            size -= 1
        return size
''',
}

RANGE_CHECKS = '''import datetime
from decimal import Decimal
from fractions import Fraction
from more_itertools import numeric_range
cases = [(0.0,1.0,0.1), (0.0,0.9,0.3), (1.0,0.0,-0.1), (4,-1,-2),
         (10**20,10**20+10,2), (Decimal('0'),Decimal('1'),Decimal('0.1')),
         (Fraction(0),Fraction(1),Fraction(1,3)), (1,1,1), (1,0,1),
         (datetime.datetime(2020,1,1),datetime.datetime(2020,1,4),datetime.timedelta(days=1))]
for args in cases:
    r = numeric_range(*args)
    values = list(r)
    assert len(r) == len(values), args
    for i,value in enumerate(values):
        assert value in r and r.index(value) == i, (args,value,i)
assert 0.35 not in numeric_range(0.0,1.0,0.1)
try:
    numeric_range(0.0,1.0,0.1).index(0.35)
except ValueError:
    pass
else:
    raise AssertionError('nonmember accepted')
print('10 range scenarios and nonmember checks passed')
'''
PROMPT_CHECKS = '''import json,sys
import click
from click.testing import CliRunner
records = []
cases = [('',False,'Count5\\n'), (': ',False,'Count: 5\\n'), ('?',False,'Count? 5\\n'),
         ('',True,'Count\\n'), (': ',True,'Count: \\n')]
for suffix,hidden,expected in cases:
    @click.command()
    def cli(): click.prompt('Count',prompt_suffix=suffix,hide_input=hidden,type=int)
    r = CliRunner().invoke(cli,input='5\\n')
    records.append({'case':'prompt','suffix':suffix,'hidden':hidden,'output':r.output,'expected':expected,
                    'passed':r.exit_code == 0 and r.output == expected})
for suffix,expected in [('', 'Proceedy\\n'), (': ','Proceed: y\\n')]:
    @click.command()
    def cli(): click.confirm('Proceed',prompt_suffix=suffix,show_default=False)
    r = CliRunner().invoke(cli,input='y\\n')
    records.append({'case':'confirm','suffix':suffix,'output':r.output,'expected':expected,
                    'passed':r.exit_code == 0 and r.output == expected})
@click.command()
def aborting(): click.confirm('Proceed',abort=True)
r = CliRunner().invoke(aborting,input='n\\n')
records.append({'case':'confirm-abort','passed':r.exit_code == 1 and 'Aborted!' in r.output})
print(json.dumps(records))
sys.exit(0 if all(r['passed'] for r in records) else 1)
'''


def human_patch(workspace, task):
    if task == 'more-range-membership':
        path = workspace / 'more_itertools/more.py'
        source = path.read_text(encoding='utf-8')
        tree = functions.declarations(ast.parse(source))
        lines = source.splitlines(keepends=True)
        for name in sorted(METHODS, key=lambda name: tree[name][0].lineno, reverse=True):
            nodes = tree[name]
            if len(nodes) != 1:
                raise ValueError('Ambiguous hypothesis target')
            node = nodes[0]
            lines[node.lineno-1:node.end_lineno] = [METHODS[name]]
        patched = ''.join(lines)
    elif task == 'click-prompt-suffix':
        path = workspace / 'src/click/termui.py'
        patched = path.read_text(encoding='utf-8')
        for old, new in [('return f(" ")', 'return f(" " if prompt_suffix else "")'),
                         ('visible_prompt_func(" ").lower().strip()',
                          'visible_prompt_func(" " if prompt_suffix else "").lower().strip()')]:
            if patched.count(old) != 1:
                raise ValueError('Nonunique human hypothesis anchor')
            patched = patched.replace(old, new, 1)
    else:
        raise ValueError('Unknown diagnosis case')
    compile(patched, str(path), 'exec')
    path.write_text(patched, encoding='utf-8')


def run(output):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    baseline.intact(manifest)
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Fresh isolated diagnosis output required')
    cases = [next(c for c in manifest['cases'] if c['task_id'] == t) for t in TASKS]
    for c in manifest['cases']:
        for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
            p = Path(c[key]).resolve()
            if output.is_relative_to(p) or p.is_relative_to(output):
                raise ValueError('Diagnosis output overlaps frozen input')
    output.mkdir(parents=True)
    report = {'complete': False, 'model_calls': 0, 'benchmark_eligible': False, 'cases': [],
              'limits': 'Hand-authored hypotheses, bounded cases; not production fixes or proof of general correctness; never model inputs'}
    for case in cases:
        root = output / case['task_id']
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        before = digest(snapshot(workspace))
        public_before = guarded.previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'before-public')
        human_patch(workspace, case['task_id'])
        public = guarded.previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'after-public')
        frozen = guarded.previous.public_check(workspace, case['frozen_harness'], case['package'], case['source_root'], root / 'after-frozen')
        checks = RANGE_CHECKS if case['task_id'] == TASKS[0] else PROMPT_CHECKS
        script = root / 'extra-checks.py'
        script.write_text(checks, encoding='utf-8')
        boot = 'import sys,runpy; sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[2],run_name="__main__")'
        extra = run_process([sys.executable, '-I', '-B', '-c', boot, str(workspace / case['source_root']), str(script)],
                            workspace, 15, root / 'extra.stdout.txt', root / 'extra.stderr.txt', test_environment(workspace))
        passed = guarded.previous.all_pass(public) and guarded.previous.all_pass(frozen) and extra['returncode'] == 0
        report['cases'].append({'task_id': case['task_id'], 'human_hypothesis_passed': passed,
                                'before_hash': before, 'candidate_hash': digest(snapshot(workspace)),
                                'public_before': public_before, 'public': public, 'frozen': frozen, 'extra': extra})
        print(case['task_id'], 'human hypothesis=', passed, flush=True)
    baseline.intact(manifest)
    report['complete'] = True
    guarded.previous.write_json(output / 'diagnosis.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output.resolve())
