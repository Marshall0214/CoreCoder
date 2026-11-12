"""Typed actions reject malformed output before any tool is invoked."""
import copy
import json

import pytest

from repairflow.feedback_actions import parse_action, schema
from repairflow.issue_tools import ToolError

VALID = [
    ('list_files', {}), ('list_files', {'pattern': '*.py', 'offset': 0}),
    ('search', {'query': 'total', 'path_glob': '*.py'}),
    ('read_file', {'path': 'pkg/calc.py'}),
    ('read_symbol', {'path': 'pkg/calc.py', 'symbol': 'Calc.total', 'offset': 6}),
    ('apply_patch', {'workspace_revision': 0, 'edits': [{'file': 'pkg/calc.py', 'old': 'old', 'new': ''}]}),
    ('finish', {}),
]


@pytest.mark.parametrize(('name', 'arguments'), VALID)
def test_valid_action_branches_keep_exact_arguments(name, arguments):
    assert parse_action(json.dumps({'action': name, 'arguments': arguments})) == (name, arguments)


@pytest.mark.parametrize(('name', 'arguments', 'field'), [
    ('read_file', {'path': 'x.py', 'offset': True}, '$.arguments.offset'),
    ('read_symbol', {'path': 'x.py', 'symbol': ''}, '$.arguments.symbol'),
    ('read_file', {'path': 'x.py', 'offset': -1}, '$.arguments.offset'),
    ('read_file', {'path': 'x.py', 'offset': 0.5}, '$.arguments.offset'),
    ('read_file', {'path': ['x.py']}, '$.arguments.path'),
    ('read_file', {'symbol': 'f'}, '$.arguments.path'),
    ('read_file', {'path': ''}, '$.arguments.path'),
    ('list_files', {'pattern': 'x' * 257}, '$.arguments.pattern'),
    ('search', {'query': ''}, '$.arguments.query'),
    ('search', {'query': 'x', 'symbol': 'f'}, '$.arguments.symbol'),
    ('finish', {'message': 'done'}, '$.arguments.message'),
    ('apply_patch', {'workspace_revision': False, 'edits': []}, '$.arguments.workspace_revision'),
    ('apply_patch', {'workspace_revision': 0, 'edits': []}, '$.arguments.edits'),
    ('apply_patch', {'workspace_revision': 0, 'edits': [{}] * 21}, '$.arguments.edits'),
    ('apply_patch', {'workspace_revision': 0, 'edits': [{'file': 'x', 'old': '', 'new': 'y'}]}, '$.arguments.edits[0].old'),
    ('apply_patch', {'workspace_revision': 0, 'edits': [{'file': 'x', 'old': 'x', 'new': 3}]}, '$.arguments.edits[0].new'),
    ('apply_patch', {'workspace_revision': 0, 'edits': [{'file': 'x', 'old': 'x', 'new': 'y', 'line': 4}]},
     '$.arguments.edits[0].line'),
])
def test_malformed_action_reports_the_exact_field(name, arguments, field):
    with pytest.raises(ToolError) as caught:
        parse_action(json.dumps({'action': name, 'arguments': arguments}))
    assert caught.value.record['code'] == 'invalid_action_schema'
    assert caught.value.record['field'] == field


@pytest.mark.parametrize('content', [
    'not JSON', '{"action":"finish","arguments":{},"action":"finish"}',
    '{"action":"read_file","arguments":{"path":"x","offset":NaN}}',
    '{"action":"read_file","arguments":{"path":"x","offset":Infinity}}',
    '{"action":"read_file","arguments":{"path":"x","path":"y"}}',
])
def test_non_json_and_ambiguous_objects_are_rejected(content):
    with pytest.raises(ToolError) as caught:
        parse_action(content)
    assert caught.value.record['code'] == 'invalid_json'


@pytest.mark.parametrize('value', [None, [], {}, {'action': 'shell', 'arguments': {}},
    {'action': 'finish', 'arguments': {}, 'tool_calls': []}])
def test_unknown_or_extra_top_level_fields_rejected(value):
    with pytest.raises(ToolError):
        parse_action(json.dumps(value))


def test_schema_branches_and_parser_share_a_spec_but_callers_get_private_copies():
    original = schema()
    assert [branch['properties']['action']['enum'][0] for branch in original['oneOf']] == [
        'list_files', 'search', 'read_file', 'read_symbol', 'apply_patch', 'finish']
    changed = copy.deepcopy(original)
    changed['oneOf'][0]['properties']['arguments']['properties']['offset']['minimum'] = -100
    assert schema() == original
    with pytest.raises(ToolError):
        parse_action('{"action":"list_files","arguments":{"offset":-1}}')
