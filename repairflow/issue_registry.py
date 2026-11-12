"""Self-contained, administrator-owned Issue entries; no HTTP uploads or fetches."""
import hashlib
import re
import shutil
from pathlib import Path

from repairflow.bundles import read, tree_hash, write
from repairflow.issue_execution import FEEDBACK, LEGACY, profile
from repairflow.issue_providers import OllamaProvider, ScriptedProvider
from repairflow.issue_repair import trusted_task


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(task_id):
    if not isinstance(task_id, str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}', task_id):
        raise ValueError('Invalid Issue task identity')
    return task_id


def hashes(root, scripted):
    result = {'prepared': tree_hash(root / 'prepared'), 'config': tree_hash(root / 'config')}
    if scripted:
        result['responses'] = sha(root / 'responses.json')
    return result


def load(root):
    root = Path(root)
    if any(path.is_symlink() or getattr(path, 'is_junction', lambda: False)() for path in (root, *root.parents)):
        raise ValueError('Linked Issue entries are unsupported')
    tree_hash(root)  # Reject linked content before reading metadata or scripted answers.
    entry = read(root / 'entry.json')
    expected = {'schema_version', 'task_id', 'model', 'observation_policy', 'scripted_responses', 'hashes'}
    if entry.get('schema_version') == 2:
        expected |= {'engine', 'execution_profile'}
        if entry.get('engine') != FEEDBACK or entry.get('execution_profile') != profile(entry.get('execution_profile')):
            raise ValueError('Unsupported Issue execution policy')
        if entry.get('observation_policy') != 'full':
            raise ValueError('Feedback execution uses its fixed context contract')
    if set(entry) != expected or entry['schema_version'] not in {1, 2} or type(entry['scripted_responses']) is not bool:
        raise ValueError('Unsupported Issue registry entry')
    if identity(entry['task_id']) != root.name:
        raise ValueError('Issue entry identity differs from its directory')
    if entry['observation_policy'] not in {'full', 'compact-v1'}:
        raise ValueError('Unknown Issue observation policy')
    OllamaProvider(entry['model'], 0)  # Validate a local model name; no request is made.
    if entry['hashes'] != hashes(root, entry['scripted_responses']):
        raise ValueError('Issue entry inputs changed')
    if entry['scripted_responses']:
        ScriptedProvider(root / 'responses.json')
    task, _ = trusted_task(root / 'prepared', root / 'config/task.json')
    return dict(entry, entry_sha256=sha(root / 'entry.json')), task


def register(prepared, configuration, output, *, model='qwen3.5:27b', observation_policy='full', responses=None,
             engine=LEGACY, execution_profile=None):
    """Copy verified admission inputs, keeping relative config paths and original hashes."""
    prepared, configuration, output = Path(prepared).resolve(), Path(configuration).resolve(), Path(output).absolute()
    identity(output.name)
    if output.exists() or output.is_symlink():
        raise ValueError('Issue registry destination must be new')
    if any(output.is_relative_to(path) or path.is_relative_to(output)
           for path in (prepared, configuration.parent)):
        raise ValueError('Registry destination overlaps task inputs')
    if observation_policy not in {'full', 'compact-v1'}:
        raise ValueError('Unknown Issue observation policy')
    if engine not in {LEGACY, FEEDBACK} or engine == LEGACY and execution_profile is not None:
        raise ValueError('Unsupported Issue execution profile')
    selected = profile(execution_profile) if engine == FEEDBACK else None
    if selected is not None and observation_policy != 'full':
        raise ValueError('Feedback execution uses its fixed context contract')
    OllamaProvider(model, 0)
    _, settings = trusted_task(prepared, configuration)
    if responses is not None:
        responses = Path(responses).resolve()
        ScriptedProvider(responses)
        if responses.is_relative_to(output):
            raise ValueError('Responses must be outside a new entry')
    output.mkdir(parents=True)
    shutil.copytree(prepared, output / 'prepared')
    (output / 'config').mkdir()
    shutil.copyfile(configuration, output / 'config/task.json')
    harness_name = read(configuration)['harness']
    shutil.copytree(settings['harness'], output / 'config' / harness_name)
    if responses is not None:
        shutil.copyfile(responses, output / 'responses.json')
    entry = {'schema_version': 1, 'task_id': output.name, 'model': model, 'observation_policy': observation_policy,
             'scripted_responses': responses is not None, 'hashes': hashes(output, responses is not None)}
    if selected is not None:
        entry.update(schema_version=2, engine=engine, execution_profile=selected)
    write(output / 'entry.json', entry)
    load(output)
    return output
