"""Versioned action schema and deterministic checks for opt-in feedback contracts."""
import copy
import json

from repairflow.issue_tools import ToolError

SCHEMA_ID = 'feedback-actions-schema-v1'


def object_schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def text(minimum=0, maximum=None):
    result = {'type': 'string', 'minLength': minimum}
    if maximum is not None:
        result['maxLength'] = maximum
    return result


def action_schema():
    offset = {'type': 'integer', 'minimum': 0}
    edit = object_schema({'file': text(1), 'old': text(1), 'new': text()}, ('file', 'old', 'new'))
    arguments = {
        'list_files': object_schema({'pattern': text(0, 256), 'offset': offset}),
        'search': object_schema({'query': text(1, 256), 'path_glob': text()}, ('query',)),
        'read_file': object_schema({'path': text(1), 'offset': offset}, ('path',)),
        'read_symbol': object_schema({'path': text(1), 'symbol': text(1, 256), 'offset': offset}, ('path', 'symbol')),
        'apply_patch': object_schema({'workspace_revision': offset,
                                     'edits': {'type': 'array', 'items': edit, 'minItems': 1, 'maxItems': 20}},
                                    ('workspace_revision', 'edits')),
        'finish': object_schema({}),
    }
    return {'oneOf': [object_schema({'action': {'type': 'string', 'enum': [name]}, 'arguments': args},
                                   ('action', 'arguments')) for name, args in arguments.items()]}


ACTION_SCHEMA = action_schema()


def schema():
    """Return a private copy, so a provider cannot change the executor's contract."""
    return copy.deepcopy(ACTION_SCHEMA)


def _check(value, spec, path):
    kind = spec['type']
    types = {'object': dict, 'array': list, 'string': str, 'integer': int}
    if type(value) is not types[kind]:
        return path, 'Expected ' + kind
    if 'enum' in spec and value not in spec['enum']:
        return path, 'Use a declared action'
    if kind == 'object':
        missing = set(spec['required']) - set(value)
        if missing:
            return path + '.' + min(missing), 'Required field is missing'
        extra = set(value) - set(spec['properties'])
        if extra:
            return path + '.' + min(extra), 'Unexpected field'
        for key, item in value.items():
            failure = _check(item, spec['properties'][key], path + '.' + key)
            if failure:
                return failure
    elif kind == 'array':
        if not spec['minItems'] <= len(value) <= spec['maxItems']:
            return path, f"Require {spec['minItems']} to {spec['maxItems']} items"
        for index, item in enumerate(value):
            failure = _check(item, spec['items'], f'{path}[{index}]')
            if failure:
                return failure
    elif kind == 'string':
        if len(value) < spec.get('minLength', 0) or len(value) > spec.get('maxLength', len(value)):
            return path, 'String length is outside the action contract'
    elif value < spec['minimum']:
        return path, 'Require a nonnegative integer'
    return None


def parse_action(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON object key')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('Non-finite JSON number')

    try:
        value = json.loads(content, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ToolError('invalid_json', 'Return one JSON action without duplicate keys or non-finite numbers.',
                        next_action='retry_action') from exc
    name = value.get('action') if isinstance(value, dict) else None
    branch = next((item for item in ACTION_SCHEMA['oneOf']
                   if item['properties']['action']['enum'] == [name]), None)
    if branch is None:
        raise ToolError('invalid_action', 'Use one of the six declared actions.', field='$.action',
                        next_action='retry_action')
    failure = _check(value, branch, '$')
    if failure:
        field, message = failure
        raise ToolError('invalid_action_schema', message, field=field, schema_id=SCHEMA_ID,
                        next_action='retry_action')
    return value['action'], value['arguments']
