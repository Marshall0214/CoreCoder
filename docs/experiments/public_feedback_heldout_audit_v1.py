"""Post-run public preservation witness; no model call or grading modification."""
import argparse
from pathlib import Path

from docs.experiments import public_feedback_heldout_v1 as experiment

WITNESS = '''"""Independent stable expectations for reusable repeated inputs."""
import unittest
from more_itertools import gray_product, partial_product

class Reproduce(unittest.TestCase):
    def test_gray_starts_with_first_values(self):
        self.assertEqual(next(gray_product([2, 3], [8, 9], repeat=2)), (2, 8, 2, 8))

class Preserve(unittest.TestCase):
    def test_partial_starts_with_first_values(self):
        self.assertEqual(next(partial_product([2, 3], [8, 9], repeat=2)), (2, 8, 2, 8))
'''


def run(source, admission, output):
    report = experiment.load(source)
    if not report['complete'] or len(report['runs']) != 40:
        raise ValueError('Audit only after the complete frozen heldout run')
    task = 'more-gray-partial-repeat'
    case = next(c for c in experiment.cases_from(admission) if c['task_id'] == task)
    root = source.resolve().parent / task
    experiment.fresh_output(output, [case], [root / 'workspace', root / 'initial-workspace'])
    harness = output / 'checks'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(WITNESS, encoding='utf-8')
    outcomes = {}
    for label, path in [('original', Path(case['before'])), ('initial', root / 'initial-workspace'),
                        ('final', root / 'workspace')]:
        outcomes[label] = experiment.policy.public_check(path, harness, case['package'], case['source_root'], output / label)
    original_valid = all(g['passed'] for g in outcomes['original'].values())
    regression = original_valid and not outcomes['final']['Preserve']['passed']
    data = {'complete': True, 'task_id': task, 'model_calls': 0,
            'known_regression': regression, 'original_expectation_validated': original_valid,
            'expectation': 'reusable repeated inputs start with (2,8,2,8), not shared-iterator (2,8,3,9)',
            'scope': 'one post-hoc witness selected by patch review; not a new full benchmark or prevalence estimate',
            'grading_changed': False, 'private_grader_used': False, 'reference_used': False,
            'source_sha256': experiment.policy.admission.history.sha(source),
            'witness_sha256': experiment.policy.admission.history.sha(harness / 'test_admission.py'), 'outcomes': outcomes}
    experiment.policy.write_json(output / 'audit.json', data)
    print('Known public preservation regression:', regression)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--admission', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.source.resolve(), args.admission.resolve(), args.output.resolve())
