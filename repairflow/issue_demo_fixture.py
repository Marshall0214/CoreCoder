"""Self-contained synthetic Issue bootstrap; no GitHub or model request is made."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from repairflow.bundles import write
from repairflow.github_issue import prepare as prepare_issue
from repairflow.issue_registry import register

REPO = 'example/corecoder-offline-demo'
COMMIT = 'd' * 40
URL = 'https://github.com/' + REPO + '/issues/1'
SOURCE = 'def f(x):\n    return x + 1\n\ndef g(x):\n    return x\n'
DEPENDENCY = 'STEP = 2\n'
HARNESS = '''import unittest
from pkg import f, g
class Reproduce(unittest.TestCase):
    def test_target(self):
        self.assertEqual(f(1), 3)
class Preserve(unittest.TestCase):
    def test_control(self):
        self.assertEqual(g(0), 0)
'''
LICENSE = ('Synthetic offline demonstration fixture authored for this project.\n'
           'No source from a real GitHub repository is included.\n')


class OfflineFixtureClient:
    """Satisfy exactly the three admission endpoints from inline data, without I/O."""

    def __init__(self):
        self.requests = []
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, content in {'src/pkg/__init__.py': SOURCE, 'src/pkg/dependency.py': DEPENDENCY,
                                  'LICENSE': LICENSE}.items():
                member = zipfile.ZipInfo('synthetic-' + COMMIT + '/' + name, (2020, 1, 1, 0, 0, 0))
                archive.writestr(member, content)
        api = 'https://api.github.com/repos/' + REPO
        issue = {'number': 1, 'html_url': URL,
                 'title': 'Synthetic offline fixture: f must return x plus two. Preserve g behavior.',
                 'body': 'This is inline demonstration data, not a fetched or historical GitHub Issue.',
                 'created_at': '2020-01-01T00:00:00Z', 'updated_at': '2020-01-01T00:00:00Z'}
        self.replies = {api + '/issues/1': json.dumps(issue).encode(),
                        api + '/git/commits/' + COMMIT: json.dumps({'sha': COMMIT,
                            'tree': {'sha': 'e' * 40}}).encode(),
                        'https://codeload.github.com/' + REPO + '/zip/' + COMMIT: buffer.getvalue()}

    def get(self, url, limit=32_000_000):
        if url not in self.replies:
            raise ValueError('Synthetic demo cannot fetch a network endpoint')
        raw = self.replies[url]
        if len(raw) > limit:
            raise ValueError('Synthetic fixture exceeds the requested response limit')
        self.requests.append(url)
        return raw


def responses():
    def action(name, **arguments):
        return json.dumps({'action': name, 'arguments': arguments})

    return [action('finish'),
            action('read_symbol', path='src/pkg/__init__.py', symbol='f'),
            action('apply_patch', workspace_revision=0,
                   edits=[{'file': 'src/pkg/__init__.py', 'old': '    return x + 1', 'new': '    return x + 0'}]),
            action('read_symbol', path='src/pkg/dependency.py', symbol='STEP'),
            action('read_symbol', path='src/pkg/__init__.py', symbol='f'),
            action('apply_patch', workspace_revision=1,
                   edits=[{'file': 'src/pkg/__init__.py', 'old': '    return x + 0',
                           'new': '    from .dependency import STEP\n    return x + STEP'}])]


def prepare(root, image='corecoder-test-sandbox:v1'):
    """Create and admit one explicit synthetic example using the existing local image."""
    root = Path(root).resolve()
    if root.exists():
        raise ValueError('Synthetic demo inputs require a fresh output directory')
    root.mkdir(parents=True)
    trusted = root / 'trusted'
    (trusted / 'checks').mkdir(parents=True)
    (trusted / 'checks/test_admission.py').write_text(HARNESS, encoding='utf-8')
    config = trusted / 'task.json'
    write(config, {'schema_version': 1, 'repo': REPO, 'issue_number': 1, 'base_commit': COMMIT,
                   'package': 'pkg', 'source_root': 'src', 'allowed_files': ['src/pkg/__init__.py'],
                   'read_only_files': ['src/pkg/dependency.py'], 'harness': 'checks',
                   'license_file': 'LICENSE', 'license_id': 'synthetic-demo-only', 'image': image})
    client = OfflineFixtureClient()
    prepared = root / 'prepared'
    admission = prepare_issue(URL, config, prepared, client=client)
    manifest = {'schema_version': 'synthetic-issue-demo-v1', 'synthetic': True,
                'scope': 'Inline engineering fixture, not a real GitHub Issue or model repair result',
                'github_identity_is_placeholder': True, 'commit_is_placeholder': True,
                'placeholder_commit': COMMIT, 'network_requests': 0, 'fresh_model_calls': 0,
                'endpoints_satisfied_in_memory': list(client.requests),
                'admission_status': admission['status'], 'ready_for_repair': admission['ready_for_repair'],
                'sandbox': admission['sandbox'], 'registry_entry': 'catalog/sample'}
    write(root / 'fixture-manifest.json', manifest)
    write(prepared / 'fixture-manifest.json', manifest)
    if not admission['ready_for_repair']:
        raise ValueError('Synthetic fixture admission failed: ' + admission['status'])
    recording = root / 'responses.json'
    write(recording, responses())
    entry = register(prepared, config, root / 'catalog/sample', responses=recording,
                     engine='feedback-actions-v2')
    write(root / 'bootstrap-receipt.json', {'fixture_manifest_sha256': hashlib.sha256(
        (root / 'fixture-manifest.json').read_bytes()).hexdigest(),
        'responses_sha256': hashlib.sha256(recording.read_bytes()).hexdigest(),
        'entry_sha256': hashlib.sha256((entry / 'entry.json').read_bytes()).hexdigest(),
        'network_requests': 0, 'fresh_model_calls': 0})
    return entry
