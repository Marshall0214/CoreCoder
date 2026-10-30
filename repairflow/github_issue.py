"""Read-only public GitHub issue admission. Never executes repository setup code."""
import hashlib
import io
import json
import re
import shutil
import stat
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from evals.schema import relative_path
from repairflow import checks
from repairflow.bundles import tree_hash, write
from sandbox import runner

ISSUE_URL = re.compile(r'https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)/?\Z')
LIMIT = 32_000_000


def identity(url):
    match = ISSUE_URL.fullmatch(url)
    if not match or match[2] in {'.', '..'}:
        raise ValueError('Require a canonical public github.com owner/repo/issues/number URL')
    return f'{match[1]}/{match[2]}', int(match[3])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('GitHub redirects require an updated canonical configuration')


class PublicGitHub:
    """Only constructed public GET endpoints; no tokens, cookies, comments or PRs."""
    def __init__(self):
        self.requests = []

    def get(self, url, limit=LIMIT):
        if not re.fullmatch(r'https://(?:api\.github\.com/repos/[A-Za-z0-9_./-]+|'
                            r'codeload\.github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/zip/[0-9a-f]{40})', url):
            raise ValueError('Unapproved GitHub download endpoint')
        self.requests.append(url)
        request = urllib.request.Request(url, headers={'User-Agent': 'CoreCoder-Issue-Preparation',
                                                       'Accept': 'application/vnd.github+json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('GitHub response exceeds size limit')
        return data


def portable(name):
    relative_path(name)
    for part in name.split('/'):
        stem = part.split('.')[0].upper()
        if (part.endswith(('.', ' ')) or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                or stem in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                            *(f'LPT{i}' for i in range(1, 10))} or part.casefold() == '.git'):
            raise ValueError('Unsafe portable repository path')
    return name


def config(path, url):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = json.loads(raw)
    expected = {'schema_version', 'repo', 'issue_number', 'base_commit', 'package', 'source_root',
                'allowed_files', 'harness', 'license_file', 'license_id', 'image'}
    if set(data) - {'read_only_files'} != expected or data['schema_version'] != 1:
        raise ValueError('Unsupported trusted issue configuration')
    repo, number = identity(url)
    if (data['repo'] != repo or type(data['issue_number']) is not int or data['issue_number'] != number
            or not re.fullmatch('[0-9a-f]{40}', data['base_commit'])
            or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', data['package'])):
        raise ValueError('Issue identity or pinned commit differs from trusted configuration')
    portable(data['source_root'])
    portable(data['license_file'])
    if not data['license_id'] or not isinstance(data['image'], str) or not data['image'] or data['image'].startswith('-'):
        raise ValueError('Require reviewed license and trusted image')
    allowed = data['allowed_files']
    if not isinstance(allowed, list) or not allowed or len(set(allowed)) != len(allowed):
        raise ValueError('Require explicit allowed source files')
    for name in allowed:
        portable(name)
        if not name.endswith('.py'):
            raise ValueError('Only Python source changes supported in this version')
    read_only = data.get('read_only_files', [])
    if (not isinstance(read_only, list) or len(read_only) > 128
            or any(not isinstance(name, str) for name in read_only)
            or len(set(read_only)) != len(read_only) or set(read_only) & set(allowed)):
        raise ValueError('Require unique read-only files distinct from writable files')
    for name in read_only:
        portable(name)
        if not name.endswith('.py'):
            raise ValueError('Read-only dependencies must be explicit Python source files')
    portable(data['harness'])
    harness = path.parent / data['harness']
    if any(p.is_symlink() for p in (harness, *harness.parents)) or not harness.resolve().is_relative_to(path.parent):
        raise ValueError('Trusted harness must stay within configuration directory')
    data.update(config_path=str(path), config_sha256=hashlib.sha256(raw).hexdigest(),
                harness=str(harness.resolve()), harness_sha256=tree_hash(harness))
    if not (harness / 'test_admission.py').is_file():
        raise ValueError('Require trusted Reproduce/Preserve unittest harness')
    return data


def extract(raw, destination):
    """Validate the entire bounded ZIP before writing regular files; never run git or setup."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members, prefixes, seen, spellings, files, total = [], set(), set(), {}, set(), 0
        if len(archive.infolist()) > 20000:
            raise ValueError('Too many archive members')
        for item in archive.infolist():
            original = item.orig_filename.rstrip('/')
            portable(original)
            parts = PurePosixPath(original).parts
            prefixes.add(parts[0])
            mode = (item.external_attr >> 16) & 0o170000
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError('Archive links and special files are unsupported')
            if len(parts) < 2:
                if not item.is_dir():
                    raise ValueError('Expected one repository archive root')
                continue
            name = '/'.join(parts[1:])
            for index in range(1, len(parts)):
                prefix = '/'.join(parts[1:index + 1])
                key = prefix.casefold()
                if key in spellings and spellings[key] != prefix:
                    raise ValueError('Case-aliased archive path')
                if key in files and (index < len(parts) - 1 or item.is_dir()):
                    raise ValueError('Archive file/directory collision')
                spellings[key] = prefix
            if item.is_dir():
                continue
            if (name.casefold() in seen or item.file_size > 1_000_000 or item.flag_bits & 1
                    or any(key.startswith(name.casefold() + '/') for key in spellings)):
                raise ValueError('Duplicate or oversized repository file')
            seen.add(name.casefold())
            files.add(name.casefold())
            total += item.file_size
            if total > 64_000_000:
                raise ValueError('Expanded repository exceeds size limit')
            members.append((item, name))
        if len(prefixes) != 1 or not members:
            raise ValueError('Expected one nonempty repository root')
        destination.mkdir()
        for item, name in members:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))


def prepare(url, configuration, output, client=None):
    """Produce an admission task, not a repair bundle or a claim of independent grading."""
    settings = config(configuration, url)
    output = Path(output).resolve()
    trusted = Path(settings['config_path']).parent
    if output.exists() or output.is_relative_to(trusted) or trusted.is_relative_to(output):
        raise ValueError('Require a fresh output outside trusted configuration inputs')
    policy = runner.preflight(settings['image'])
    output.mkdir(parents=True)
    client = client or PublicGitHub()
    task = {'schema_version': 'github-issue-preparation-v1', 'repo': settings['repo'],
            'issue_url': url.rstrip('/'), 'base_commit': settings['base_commit'],
            'fetched_at': datetime.now(timezone.utc).isoformat(), 'status': 'preparing',
            'ready_for_repair': False, 'independent_grading_available': False,
            'fresh_model_calls': 0, 'sandbox': policy, 'config_sha256': settings['config_sha256']}
    stage = 'github_fetch'
    try:
        api = 'https://api.github.com/repos/' + settings['repo']
        raw_issue = client.get(api + '/issues/' + str(settings['issue_number']), 2_000_000)
        issue = json.loads(raw_issue)
        if ('pull_request' in issue or identity(issue['html_url']) != identity(url)
                or issue['number'] != settings['issue_number'] or not isinstance(issue['title'], str)
                or issue.get('body') is not None and not isinstance(issue['body'], str)):
            raise ValueError('Require a matching Issue, not a pull request')
        # Deliberately omit timeline, comments, PR metadata and author/account data.
        issue = {k: issue.get(k) for k in ('number', 'html_url', 'title', 'body', 'created_at', 'updated_at')}
        write(output / 'issue.json', issue)
        task['issue_sha256'] = hashlib.sha256((output / 'issue.json').read_bytes()).hexdigest()
        commit = json.loads(client.get(api + '/git/commits/' + settings['base_commit'], 2_000_000))
        if commit['sha'] != settings['base_commit']:
            raise ValueError('Repository commit identity mismatch')
        task['commit_tree'] = commit['tree']['sha']
        archive = client.get(f"https://codeload.github.com/{settings['repo']}/zip/{settings['base_commit']}")
        task['archive_sha256'] = hashlib.sha256(archive).hexdigest()
        stage = 'source_prepare'
        source = output / 'source'
        extract(archive, source)
        if not (source / settings['source_root'] / settings['package'] / '__init__.py').is_file():
            raise ValueError('Configured package not found in pinned source')
        for name in settings['allowed_files'] + settings.get('read_only_files', []):
            if not (source / name).is_file():
                raise ValueError('Allowed source missing from pinned revision')
        license_path = source / settings['license_file']
        if not license_path.is_file() or not license_path.stat().st_size:
            raise ValueError('Configured license is missing')
        task.update(license_id=settings['license_id'], license_sha256=hashlib.sha256(license_path.read_bytes()).hexdigest())
        harness = output / 'public'
        shutil.copytree(settings['harness'], harness)
        source_hash, harness_hash = tree_hash(source), tree_hash(harness)
        if harness_hash != settings['harness_sha256']:
            raise ValueError('Trusted checks changed while copying')
        stage = 'sandbox_admission'
        logs = output / 'admission'
        logs.mkdir()
        outcomes = {}
        for name in ('Reproduce', 'Preserve'):
            outcomes[name] = runner.run(source, harness, settings['package'], settings['source_root'], logs,
                                        name, checks.historical.admission.previous.BOOT, policy, runner.owner(output))
        target, control = outcomes['Reproduce'], outcomes['Preserve']
        clean = lambda row: (row['tests_run'] > 0 and row['errors'] == 0 and not row['skipped']
                             and not row['expected_failures'] and not row['unexpected_successes'])
        reproduced = clean(target) and target['returncode'] == 1 and target['failures'] > 0 and not target['successful']
        preserved = clean(control) and control['returncode'] == 0 and control['successful'] and control['failures'] == 0
        if source_hash != tree_hash(source) or harness_hash != tree_hash(harness):
            raise ValueError('Inputs changed during admission')
        task.update(status='ready_for_repair' if reproduced and preserved else 'baseline_regression' if not preserved
                    else 'not_reproduced' if target['successful'] else 'invalid_check_execution',
                    ready_for_repair=bool(reproduced and preserved), reproduction_failed_on_base=bool(reproduced),
                    preservation_passed=bool(preserved), checks=outcomes, source_sha256=source_hash,
                    harness_sha256=harness_hash, package=settings['package'], source_root=settings['source_root'],
                    allowed_files=settings['allowed_files'], description=issue['title'] + '\n\n' + (issue['body'] or ''))
        if 'read_only_files' in settings:
            task['read_only_files'] = settings['read_only_files']
    except runner.SandboxError as exc:
        task.update(status=exc.status, failure_stage=stage)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, urllib.error.URLError) as exc:
        task.update(status=stage + '_failed', failure_stage=stage, failure_type=type(exc).__name__)
    task['requested_urls'] = client.requests
    task['evidence_scope'] = 'Trusted public reproduction and preservation only; no reference fix or independent grader.'
    task['issue_text_scope'] = 'Title/body as fetched, may have upstream edits; untrusted data, not execution instructions.'
    write(output / 'task.json', task)
    write(output / 'report.json', {k: v for k, v in task.items() if k != 'description'})
    return task


def load_prepared(root):
    """Verify retained admission inputs before a later stage consumes them; not authorization."""
    root = Path(root).resolve()
    if (root / 'task.json').is_symlink() or (root / 'issue.json').is_symlink():
        raise ValueError('Linked preparation metadata is unsupported')
    task = json.loads((root / 'task.json').read_text(encoding='utf-8'))
    if (task.get('schema_version') != 'github-issue-preparation-v1' or task.get('ready_for_repair') is not True
            or task.get('status') != 'ready_for_repair' or task.get('independent_grading_available') is not False):
        raise ValueError('Task has not passed public admission')
    for name, key in [('source', 'source_sha256'), ('public', 'harness_sha256')]:
        if tree_hash(root / name) != task[key]:
            raise ValueError('Prepared input changed: ' + name)
    if hashlib.sha256((root / 'issue.json').read_bytes()).hexdigest() != task['issue_sha256']:
        raise ValueError('Prepared issue changed')
    task['task_sha256'] = hashlib.sha256((root / 'task.json').read_bytes()).hexdigest()
    return task
