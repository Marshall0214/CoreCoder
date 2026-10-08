"""Post-hoc Context stack regression audit; never used to select this experiment's patches."""
import argparse
import json
from pathlib import Path

from docs.experiments import frozen_feedback_compare_v1 as comparison
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

CODE = '''import unittest
import click

class Controls(unittest.TestCase):
    def test_normal_exit_pops_context(self):
        self.assertIsNone(click.get_current_context(silent=True))
        with click.Context(click.Command('outer')) as ctx:
            self.assertIs(click.get_current_context(), ctx)
        self.assertIsNone(click.get_current_context(silent=True))

    def test_nested_exit_restores_outer_context(self):
        with click.Context(click.Command('outer')) as outer:
            with click.Context(click.Command('inner')) as inner:
                self.assertIs(click.get_current_context(), inner)
            self.assertIs(click.get_current_context(), outer)
        self.assertIsNone(click.get_current_context(silent=True))

    def test_exceptional_exit_pops_context(self):
        with self.assertRaises(ValueError):
            with click.Context(click.Command('error')):
                raise ValueError('control')
        self.assertIsNone(click.get_current_context(silent=True))
'''


def run(admission, experiment, output):
    data = comparison.replay.load(experiment)
    if not data['complete'] or output.exists():
        raise ValueError('Require complete experiment and fresh output')
    case = next(c for c in comparison.replay.load(admission)['cases'] if c['task_id'] == 'click-resource-exception')
    sources = {'before': Path(case['before']), 'reference': Path(case['after'])}
    sources.update({p: experiment.parent / case['task_id'] / p / 'workspace' for p in comparison.POLICIES})
    output = output.resolve()
    if any(output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in sources.values()):
        raise ValueError('Output overlaps source')
    output.mkdir(parents=True)
    harness = output / 'checks'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(CODE, encoding='utf-8')
    original_hashes = {k: digest(snapshot(p)) for k, p in sources.items()}
    if original_hashes['before'] != case['before_hash'] or original_hashes['reference'] != case['after_hash']:
        raise ValueError('Frozen source changed')
    rows = {}
    admission_module = comparison.previous.admission
    for label, source in sources.items():
        logs = output / label
        logs.mkdir()
        record = logs / 'Controls.json'
        process = run_process([str(admission_module.PYTHON), '-I', '-B', '-c', admission_module.previous.BOOT,
                               str((source / case['source_root']).resolve()), str(harness), case['package'],
                               'Controls', str(record)], source, 15, logs / 'stdout.txt', logs / 'stderr.txt',
                              test_environment(source))
        score = comparison.replay.load(record) if record.exists() else {}
        passed = (process['returncode'] == 0 and not process['timed_out'] and score.get('tests_run') == 3
                  and score.get('successful') and not any(score.get(k, 0) for k in
                  ('skipped', 'expected_failures', 'unexpected_successes', 'errors', 'failures')))
        rows[label] = dict(process, **score, passed=bool(passed))
    if original_hashes != {k: digest(snapshot(p)) for k, p in sources.items()}:
        raise ValueError('Audit mutated source')
    report = {'complete': True, 'task_id': case['task_id'], 'checks': rows,
              'certified': rows['before']['passed'] and rows['reference']['passed'],
              'source_hashes': original_hashes, 'harness_hash': digest(snapshot(harness)),
              'experiment_sha256': comparison.previous.admission.history.sha(experiment),
              'model_calls': 0,
              'limits': 'Post-hoc audit after inspecting gained patch; not predeclared scoring or blind validation'}
    comparison.previous.write_json(output / 'audit.json', report)
    print(json.dumps({k: r['passed'] for k, r in rows.items()}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('admission', 'experiment', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.admission, args.experiment, args.output)
