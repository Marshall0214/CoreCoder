"""Small self-contained Issue entry; no network, model, or historical task assets."""
from repairflow.bundles import read, write
from repairflow.github_issue import prepare
from tests.issue_repair_fixture import HARNESS, SOURCE, IssueClient, patch
from tests.test_github_issue import URL, configuration, zipped


def admitted(tmp_path, image=None):
    configuration_path = configuration(tmp_path)
    data = read(configuration_path)
    data['read_only_files'] = ['src/pkg/dependency.py']
    if image:
        data['image'] = image
    write(configuration_path, data)
    (configuration_path.parent / 'checks/test_admission.py').write_text(HARNESS, encoding='utf-8')
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
