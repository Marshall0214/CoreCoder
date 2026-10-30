"""Public-only admitted source; no historical assets or independent grader."""
import json

from repairflow.bundles import read, write
from repairflow.github_issue import prepare
from tests.test_github_issue import URL, Client, configuration, zipped

SOURCE = 'def f(x):\n    return x + 1\n\ndef g(x):\n    return x\n'
HARNESS = '''import unittest
from pkg import f, g
class Reproduce(unittest.TestCase):
    def test_target(self):
        self.assertEqual(f(1), 3)
class Preserve(unittest.TestCase):
    def test_control(self):
        self.assertEqual(g(0), 0)
'''


class IssueClient(Client):
    def get(self, url, limit=32_000_000):
        raw = super().get(url, limit)
        if '/issues/' in url:
            issue = json.loads(raw)
            issue.update(title='f must return x plus two. Preserve g behavior.', body='')
            return json.dumps(issue).encode()
        return raw


def prepare_fixture(tmp_path, image=None, *, source=SOURCE):
    configuration_path = configuration(tmp_path)
    if image:
        data = read(configuration_path)
        data['image'] = image
        write(configuration_path, data)
    (configuration_path.parent / 'checks/test_admission.py').write_text(HARNESS, encoding='utf-8')
    client = IssueClient(archive=zipped({'src/pkg/__init__.py': source, 'LICENSE': 'Example license'}))
    root = tmp_path / 'prepared'
    task = prepare(URL, configuration_path, root, client)
    assert task['ready_for_repair']
    return root, configuration_path


def patch(old=1, new=2):
    return json.dumps({'edits': [{'file': 'src/pkg/__init__.py', 'old': f'    return x + {old}',
                               'new': f'    return x + {new}'}]})
