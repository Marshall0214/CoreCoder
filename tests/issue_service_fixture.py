"""Small self-contained Issue entry; no network, model, or historical task assets."""
from repairflow.bundles import read, write
from repairflow.github_issue import prepare
from tests.issue_repair_fixture import HARNESS, SOURCE, IssueClient, patch
from tests.test_github_issue import URL, configuration, zipped


def admitted(tmp_path, image=None, *, harness=HARNESS):
    configuration_path = configuration(tmp_path)
    data = read(configuration_path)
    data['read_only_files'] = ['src/pkg/dependency.py']
    if image:
        data['image'] = image
    write(configuration_path, data)
    (configuration_path.parent / 'checks/test_admission.py').write_text(harness, encoding='utf-8')
    files = {'src/pkg/__init__.py': SOURCE, 'src/pkg/dependency.py': 'STEP = 2\n', 'LICENSE': 'Example license'}
    prepared = tmp_path / 'prepared'
    task = prepare(URL, configuration_path, prepared, IssueClient(archive=zipped(files)))
    assert task['ready_for_repair']
    return prepared, configuration_path


def responses(path, succeeds=True):
    import json

    read = json.dumps({'action': 'read_symbol', 'arguments': {'path': 'src/pkg/dependency.py', 'symbol': 'STEP'}})
    write(path, [read, patch()] if succeeds else [read, '{"action":"finish","arguments":{}}'])
    return path


def feedback_responses(path, *, succeeds=True):
    """Initial finish, then a real bad-edit/read-dependency/correct-edit cycle."""
    import json

    def action(name, **arguments):
        return json.dumps({'action': name, 'arguments': arguments})

    rows = [action('finish')]
    if succeeds:
        rows.extend([
            action('read_symbol', path='src/pkg/__init__.py', symbol='f'),
            action('apply_patch', workspace_revision=0,
                   edits=[{'file': 'src/pkg/__init__.py', 'old': '    return x + 1', 'new': '    return x + 0'}]),
            action('read_symbol', path='src/pkg/dependency.py', symbol='STEP'),
            action('read_symbol', path='src/pkg/__init__.py', symbol='f'),
            action('apply_patch', workspace_revision=1,
                   edits=[{'file': 'src/pkg/__init__.py', 'old': '    return x + 0',
                           'new': '    from .dependency import STEP\n    return x + STEP'}]),
        ])
    else:
        rows.append(action('finish'))
    write(path, rows)
    return path


def delayed_feedback_harness(seconds=60):
    """Admission stays quick; only an exported execution workspace sleeps."""
    delay = (f'if "workspace" in __import__("pathlib").Path(__import__("pkg").__file__).parts:'
             f'\n            __import__("time").sleep({seconds})\n        ')
    return HARNESS.replace('self.assertEqual(f(1), 3)', delay + 'self.assertEqual(f(1), 3)')
