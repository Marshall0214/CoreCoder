"""Create a SYNTHETIC offline Issue entry; never fetch GitHub or invoke a model."""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repairflow.bundles import read, write
from repairflow.github_issue import prepare
from repairflow.issue_registry import register

URL = 'https://github.com/example/issue-demo/issues/1'
COMMIT = '0' * 40  # Fixture identity only, never asserted as a real remote revision.
SOURCE = 'def add_step(x):\n    return x + 1\n\ndef echo(x):\n    return x\n'
CHECKS = '''import unittest
from example import add_step, echo
class Reproduce(unittest.TestCase):
    def test_step(self): self.assertEqual(add_step(1), 3)
class Preserve(unittest.TestCase):
    def test_echo(self): self.assertEqual(echo("unchanged"), "unchanged")
'''


class LocalFixture:
    def __init__(self):
        self.requests = []  # No HTTP requests are performed.

    def get(self, endpoint, limit=32_000_000):
        if '/issues/' in endpoint:
            return json.dumps({'html_url': URL, 'number': 1, 'title': '[SYNTHETIC DEMO] add_step must add STEP',
                               'body': 'Read policy.STEP; preserve echo. This is a local engineering demo.'}).encode()
        if '/git/commits/' in endpoint:
            return json.dumps({'sha': COMMIT, 'tree': {'sha': '0' * 40}}).encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, content in {'src/example/__init__.py': SOURCE, 'src/example/policy.py': 'STEP = 2\n',
                                  'LICENSE': 'Local synthetic demonstration fixture, released under MIT.\n'}.items():
                archive.writestr('issue-demo/' + name, content)
        return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--image', default='corecoder-test-sandbox:v1')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Use a new project .tmp output directory')
    trusted = output / 'trusted'
    (trusted / 'checks').mkdir(parents=True)
    (trusted / 'checks/test_admission.py').write_text(CHECKS, encoding='utf-8')
    configuration = trusted / 'task.json'
    write(configuration, {'schema_version': 1, 'repo': 'example/issue-demo', 'issue_number': 1,
          'base_commit': COMMIT, 'package': 'example', 'source_root': 'src',
          'allowed_files': ['src/example/__init__.py'], 'read_only_files': ['src/example/policy.py'],
          'harness': 'checks', 'license_file': 'LICENSE', 'license_id': 'MIT', 'image': args.image})
    prepared = output / 'prepared'
    task = prepare(URL, configuration, prepared, LocalFixture())
    if not task['ready_for_repair']:
        raise ValueError('Synthetic demo failed Docker admission')
    task.update(preparation_mode='synthetic_offline_demo_no_http',
                evidence_scope='Synthetic fixture only; no real GitHub source or independent grading.')
    write(prepared / 'task.json', task)
    write(prepared / 'report.json', {key: value for key, value in task.items() if key != 'description'})
    answers = output / 'responses.json'
    write(answers, [json.dumps({'action': 'read_symbol', 'arguments': {'path': 'src/example/policy.py', 'symbol': 'STEP'}}),
                    json.dumps({'edits': [{'file': 'src/example/__init__.py', 'old': '    return x + 1',
                                          'new': '    return x + 2'}]})])
    entry = register(prepared, configuration, output / 'catalog/sample', responses=answers, observation_policy='compact-v1')
    if read(entry / 'entry.json')['scripted_responses'] is not True:
        raise ValueError('Demo must remain scripted')
    print(json.dumps({'entry': str(entry), 'synthetic': True, 'http_requests': 0, 'fresh_model_calls': 0}))


if __name__ == '__main__':
    main()
