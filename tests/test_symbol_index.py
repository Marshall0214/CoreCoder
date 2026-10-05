import json

import pytest

from evals.runtime import Events
from evals.symbol_context import symbol_evidence
from evals.symbol_index import PythonCodeIndex, expand_query


def test_query_policies_do_not_add_task_specific_locations():
    query = 'Environment-variable flag_value uses Boolean activation.'
    assert expand_query(query, 'plain') == query
    assert expand_query(query, 'aliases') == query + '\nenvvar bool'
    assert expand_query(query, 'identifiers') == 'envvar bool flag_value'
    assert expand_query('Repair the reported behavior.', 'identifiers') == 'Repair the reported behavior.'
    with pytest.raises(ValueError):
        expand_query(query, 'oracle')


def test_python_corpus_is_identical_and_docs_do_not_enter_scores(tmp_path):
    (tmp_path / 'code.py').write_text('class Service:\n    def lookup(self):\n        return 1\n')
    (tmp_path / 'README.md').write_text('needle ' * 1000)
    indices = [PythonCodeIndex(tmp_path, ['code.py'], mode) for mode in ('lines', 'symbols')]
    metadata = [index.refresh() for index in indices]
    assert metadata[0]['source_hash'] == metadata[1]['source_hash']
    assert metadata[0]['index_hash'] != metadata[1]['index_hash']
    assert all(not index.rank('needle') for index in indices)
    method = next(chunk for chunk in indices[1].chunks if chunk.start_line == 2)
    header = next(chunk for chunk in indices[1].chunks if chunk.start_line == 1)
    assert 'def lookup' in method.content and 'def lookup' not in header.content


def test_symbol_index_retains_module_constants_and_invalid_source(tmp_path):
    (tmp_path / 'code.py').write_text('SETTING = "needle"\ndef run():\n    return 1\n')
    (tmp_path / 'broken.py').write_text('def needle(:\n')
    index = PythonCodeIndex(tmp_path, ['code.py', 'broken.py'], 'symbols')
    index.refresh()
    assert {chunk.path for _, chunk in index.rank('needle')} == {'code.py', 'broken.py'}


def test_symbol_query_returns_versioned_complete_method_and_local_dependency(tmp_path):
    files = {'src/pkg/entry.py': 'from .helper import normalize\n'
             'class Service:\n    def envvar(self, value):\n        return normalize(value)\n',
             'src/pkg/helper.py': 'raise RuntimeError("do not execute")\n'
             'def normalize(value):\n    return bool(value)\n'}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    events = Events(tmp_path / 'trace.jsonl', 'symbols')
    evidence = symbol_evidence(tmp_path, 'Read the environment variable.', list(files), events,
                               top_k=1, index_mode='symbols', query_policy='identifiers')
    assert [row['symbol'] for row in evidence] == ['Service.envvar', 'normalize']
    assert all(row['complete_symbol'] for row in evidence)
    trace = json.loads(events.path.read_text())
    assert trace['query'] == 'envvar' and trace['public_description'] == 'Read the environment variable.'
    assert trace['index_mode'] == 'symbols'
