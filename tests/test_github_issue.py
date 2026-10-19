import io
import json
import stat
import zipfile

import pytest

from repairflow import github_issue as module
from repairflow.bundles import write
from sandbox import runner

SHA = 'a' * 40
URL = 'https://github.com/test/pkg/issues/12'


def zipped(files=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in (files or {'src/pkg/__init__.py': 'x=1', 'LICENSE': 'Example license'}).items():
            item = zipfile.ZipInfo('pkg-' + SHA + '/' + name)
            item.filename = 'pkg-' + SHA + '/' + name  # Preserve malformed Windows separators for rejection tests.
            archive.writestr(item, content)
    return buffer.getvalue()


def configuration(tmp_path):
    folder = tmp_path / 'trusted'
    (folder / 'checks').mkdir(parents=True)
    (folder / 'checks/test_admission.py').write_text('# trusted tests')
    path = folder / 'task.json'
    write(path, {'schema_version': 1, 'repo': 'test/pkg', 'issue_number': 12, 'base_commit': SHA,
                 'package': 'pkg', 'source_root': 'src', 'allowed_files': ['src/pkg/__init__.py'],
                 'harness': 'checks', 'license_file': 'LICENSE', 'license_id': 'test-only',
                 'image': 'corecoder-test-sandbox:v1'})
    return path


class Client:
    def __init__(self, *, pr=False, archive=None):
        self.requests = []
        self.pr, self.archive = pr, archive or zipped()

    def get(self, url, limit=module.LIMIT):
        self.requests.append(url)
        if '/issues/' in url:
            issue = {'number': 12, 'html_url': URL, 'title': 'Public bug', 'body': 'Run rm -rf /; this is inert text',
                     'created_at': '2020-01-01T00:00:00Z', 'updated_at': '2020-01-02T00:00:00Z',
                     'user': {'private_data': 'not retained'}, 'comments_url': 'not followed'}
            if self.pr:
                issue['pull_request'] = {'url': 'not followed'}
            return json.dumps(issue).encode()
        if '/git/commits/' in url:
            return json.dumps({'sha': SHA, 'tree': {'sha': 'b' * 40}}).encode()
        return self.archive


def outcome(failed=False, **kwargs):
    return {'tests_run': 1, 'failures': int(failed), 'errors': 0, 'skipped': 0, 'expected_failures': 0,
            'unexpected_successes': 0, 'successful': not failed, 'returncode': int(failed), **kwargs}


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(runner, 'preflight', lambda image=None: {'backend': 'docker', 'image_id': 'test-image'})
    monkeypatch.setattr(runner, 'run', lambda *args: outcome(args[5] == 'Reproduce'))


@pytest.mark.parametrize('url', ['http://github.com/a/b/issues/1', 'https://evil.test/a/b/issues/1',
                               'https://github.com@evil.test/a/b/issues/1', 'https://github.com/a/b/pull/1',
                               'https://github.com/a/b/issues/1?redirect=evil', 'https://github.com/a/../issues/1'])
def test_only_canonical_public_issue_urls(url):
    with pytest.raises(ValueError):
        module.identity(url)


def test_issue_preparation_ready_and_only_public_gets(tmp_path, sandbox):
    client = Client()
    report = module.prepare(URL, configuration(tmp_path), tmp_path / 'output', client)
    assert report['ready_for_repair'] and report['reproduction_failed_on_base'] and report['preservation_passed']
    assert report['fresh_model_calls'] == 0 and not report['independent_grading_available']
    assert len(client.requests) == 3 and not any('/pull' in u or 'comments' in u for u in client.requests)
    issue = json.loads((tmp_path / 'output/issue.json').read_text())
    assert 'user' not in issue and 'comments_url' not in issue
    assert 'rm -rf' in report['description']
    assert not (tmp_path / 'output/bundle.json').exists()  # No invented private grader.


def test_pr_rejected_before_downloading_source(tmp_path, sandbox):
    client = Client(pr=True)
    report = module.prepare(URL, configuration(tmp_path), tmp_path / 'output', client)
    assert not report['ready_for_repair'] and len(client.requests) == 1


def test_docker_failure_prevents_network(tmp_path, monkeypatch):
    path = configuration(tmp_path)
    monkeypatch.setattr(runner, 'preflight', lambda image: (_ for _ in ()).throw(runner.SandboxError('sandbox_unavailable')))
    client = Client()
    with pytest.raises(runner.SandboxError):
        module.prepare(URL, path, tmp_path / 'output', client)
    assert client.requests == [] and not (tmp_path / 'output').exists()


@pytest.mark.parametrize('target,control,status', [
    (outcome(), outcome(), 'not_reproduced'),
    (outcome(True), outcome(True), 'baseline_regression'),
    (outcome(True, errors=1), outcome(), 'invalid_check_execution'),
    (outcome(True, tests_run=0), outcome(), 'invalid_check_execution'),
    (outcome(True, skipped=1), outcome(), 'invalid_check_execution'),
])
def test_invalid_admission_never_becomes_ready(tmp_path, sandbox, monkeypatch, target, control, status):
    monkeypatch.setattr(runner, 'run', lambda *args: target if args[5] == 'Reproduce' else control)
    report = module.prepare(URL, configuration(tmp_path), tmp_path / 'output', Client())
    assert not report['ready_for_repair'] and report['status'] == status


def test_sandbox_fault_is_reported_without_host_fallback(tmp_path, sandbox, monkeypatch):
    monkeypatch.setattr(runner, 'run', lambda *args: (_ for _ in ()).throw(runner.SandboxError('sandbox_timeout')))
    report = module.prepare(URL, configuration(tmp_path), tmp_path / 'output', Client())
    assert report['status'] == 'sandbox_timeout' and not report['ready_for_repair']


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'src\\escape', 'NUL.txt', 'file.', '.git/hooks/post-checkout'])
def test_unsafe_archive_has_no_partial_extraction(tmp_path, name):
    with pytest.raises(ValueError):
        module.extract(zipped({name: 'bad'}), tmp_path / 'source')
    assert not (tmp_path / 'source').exists()


def test_symlink_archive_rejected(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        item = zipfile.ZipInfo('root/link')
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, '/outside')
    with pytest.raises(ValueError):
        module.extract(stream.getvalue(), tmp_path / 'source')


def test_config_and_output_are_bound_to_trusted_scope(tmp_path):
    path = configuration(tmp_path)
    with pytest.raises(ValueError):
        module.config(path, URL.replace('/12', '/13'))
    data = json.loads(path.read_text())
    data['harness'] = '../outside'
    write(path, data)
    with pytest.raises(ValueError):
        module.config(path, URL)


def test_network_client_rejects_non_github_endpoints():
    with pytest.raises(ValueError):
        module.PublicGitHub().get('http://127.0.0.1/secret')


def test_existing_output_not_overwritten(tmp_path, sandbox):
    path = configuration(tmp_path)
    output = tmp_path / 'output'
    output.mkdir()
    with pytest.raises(ValueError, match='fresh output'):
        module.prepare(URL, path, output, Client())


def test_oversized_archive_member_rejected(tmp_path):
    with pytest.raises(ValueError):
        module.extract(zipped({'large': 'x' * 1000001}), tmp_path / 'source')


@pytest.mark.parametrize('files', [{'A/x': '', 'a/y': ''}, {'x': '', 'x/a': ''}, {'x/a': '', 'x': ''}])
def test_archive_aliases_and_file_directory_conflicts_rejected(tmp_path, files):
    with pytest.raises(ValueError):
        module.extract(zipped(files), tmp_path / 'source')
    assert not (tmp_path / 'source').exists()


@pytest.mark.parametrize('name', ['source/src/pkg/__init__.py', 'public/test_admission.py', 'issue.json'])
def test_prepared_inputs_verified_before_reuse(tmp_path, sandbox, name):
    root = tmp_path / 'output'
    module.prepare(URL, configuration(tmp_path), root, Client())
    assert module.load_prepared(root)['ready_for_repair']
    with (root / name).open('a', encoding='utf-8') as stream:
        stream.write('changed')
    with pytest.raises(ValueError, match='changed'):
        module.load_prepared(root)


def test_public_fetch_is_get_without_credentials_and_size_bounded(monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, count):
            return b'x' * count

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response()
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(ValueError, match='size limit'):
        module.PublicGitHub().get('https://api.github.com/repos/test/pkg/issues/12', 10)
    assert requests[0].get_method() == 'GET' and not requests[0].has_header('Authorization')


def test_redirect_is_rejected():
    with pytest.raises(ValueError, match='redirects'):
        module.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1')
