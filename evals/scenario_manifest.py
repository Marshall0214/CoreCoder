"""Source-linked scenario declarations and bounded AST shape diagnostics."""

import ast
import json

PROTOCOL = 'public-contract-feedback-v7-manifest'
KINDS = ('shared-identifier', 'duplicate-before-new', 'persistent-replay')
RULES = (
    ' Return exactly {"code":"unittest source","scenarios":[...]} instead of code alone. '
    'Include one scenario row per kind: shared-identifier, duplicate-before-new, persistent-replay. '
    'Each row has kind, status (implemented or omitted), test (Class.test_method or empty), '
    'contract_ids (public catalog IDs), identifier_field, scope_field and reason. '
    'Fields name literal record dictionary keys, not variables. Use empty strings for unknown fields. '
    'Implement only scenarios supported by cited contracts; otherwise mark omitted and explain. '
    'Use literal record dictionaries/lists or simple local assignments. Shared-identifier MUST use '
    'the SAME ID in DIFFERENT scopes. Duplicate-before-new MUST put a repeated scoped ID before '
    'a distinct later record in the SAME API call. Persistent-replay MUST use the same caller state '
    'across calls, replay an earlier scoped ID and append a new record, capture each API return with '
    'dict(api(...)) or list(api(...)), and assert the independent snapshots. '
    'Do not mark implemented just because a test name mentions the scenario.'
)


def response_format(catalog):
    fields = {'kind': {'type': 'string', 'enum': list(KINDS)},
              'status': {'type': 'string', 'enum': ['implemented', 'omitted']},
              'test': {'type': 'string', 'maxLength': 200},
              'contract_ids': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string', 'enum': [r['id'] for r in catalog]}},
              'identifier_field': {'type': 'string', 'maxLength': 80},
              'scope_field': {'type': 'string', 'maxLength': 80},
              'reason': {'type': 'string', 'maxLength': 200}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['code', 'scenarios'],
              'properties': {'code': {'type': 'string', 'minLength': 1, 'maxLength': 16000},
                             'scenarios': {'type': 'array', 'minItems': 3, 'maxItems': 3,
                                           'items': {'type': 'object', 'additionalProperties': False,
                                                     'required': list(fields), 'properties': fields}}}}
    return {'type': 'json_schema', 'json_schema': {'name': 'public_scenario_checks', 'strict': True, 'schema': schema}}


def parse_manifest(content, catalog):
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {'code', 'scenarios'} or not isinstance(parsed['code'], str):
        raise ValueError('Expected code and scenarios')
    rows = parsed['scenarios']
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError('Expected exactly three scenario declarations')
    ids = {r['id'] for r in catalog}
    seen = set()
    required = {'kind', 'status', 'test', 'contract_ids', 'identifier_field', 'scope_field', 'reason'}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError('Invalid scenario fields')
        for field in required - {'contract_ids'}:
            if not isinstance(row[field], str) or len(row[field]) > (80 if field.endswith('_field') else 200):
                raise ValueError('Invalid scenario text')
        if row['kind'] not in KINDS or row['kind'] in seen or row['status'] not in {'implemented', 'omitted'}:
            raise ValueError('Invalid or duplicate scenario kind/status')
        seen.add(row['kind'])
        refs = row['contract_ids']
        if (not isinstance(refs, list) or len(refs) > 8 or not all(isinstance(x, str) and x in ids for x in refs)
                or len(set(refs)) != len(refs) or not row['reason'].strip()):
            raise ValueError('Invalid scenario provenance')
        if row['status'] == 'implemented' and (not refs or not row['test'] or not row['identifier_field'] or not row['scope_field']):
            raise ValueError('Implemented scenario requires source, method and record fields')
        if row['status'] == 'omitted' and row['test']:
            raise ValueError('Omitted scenario cannot claim a method')
    return parsed['code'], rows


def diagnose(code, rows):
    methods = {}
    if code:
        tree = ast.parse(code)
        imports = {alias.asname or alias.name for n in tree.body if isinstance(n, ast.ImportFrom) and n.module != 'unittest'
                   for alias in n.names}
        imports |= {alias.asname or alias.name.split('.')[0] for n in tree.body if isinstance(n, ast.Import) and n.names
                    for alias in n.names if alias.name != 'unittest'}
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef):
                methods.update({f'{cls.name}.{n.name}': n for n in cls.body if isinstance(n, ast.FunctionDef)})
    result = []
    for row in rows:
        item = dict(row, observation='unknown', semantic_correctness_verified=False)
        method = methods.get(row['test'])
        if row['status'] == 'omitted':
            item['observation'] = 'declared-omitted'
        elif method is None:
            item['observation'] = 'method-missing-or-filtered'
        else:
            values, epochs, calls, snapshots, asserted = {}, {}, [], [], set()

            def resolve(node, values=values):
                if isinstance(node, ast.Name):
                    return values.get(node.id)
                if isinstance(node, ast.List):
                    return [resolve(x) for x in node.elts]
                if isinstance(node, ast.Dict):
                    try:
                        return {ast.literal_eval(k): ast.literal_eval(v) for k, v in zip(node.keys, node.values)}
                    except (ValueError, TypeError):
                        return None
                return None

            for statement in method.body:
                nodes = list(ast.walk(statement))
                api_calls = [n for n in nodes if isinstance(n, ast.Call)
                             and any(isinstance(x, ast.Name) and x.id in imports for x in ast.walk(n.func))]
                for call in api_calls:
                    args = [*call.args, *(k.value for k in call.keywords)]
                    records = [resolve(arg) for arg in args]
                    sequence = next((x for x in records if isinstance(x, list) and x and all(isinstance(r, dict) for r in x)), None)
                    names = {(arg.id, epochs.get(arg.id, 0)) for arg in args
                             if isinstance(arg, ast.Name) and not isinstance(resolve(arg), list)}
                    calls.append((sequence, names))
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, (ast.Tuple, ast.List)):
                            for name in (x.id for x in ast.walk(target) if isinstance(x, ast.Name)):
                                values.pop(name, None)
                                epochs[name] = epochs.get(name, 0) + 1
                        if isinstance(target, ast.Name):
                            values[target.id] = resolve(statement.value)
                            epochs[target.id] = epochs.get(target.id, 0) + 1
                            value = statement.value
                            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {'dict', 'list'}
                                    and len(value.args) == 1 and value.args[0] in api_calls):
                                snapshots.append(target.id)
                for n in nodes:
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert'):
                        asserted |= {x.id for arg in n.args for x in ast.walk(arg) if isinstance(x, ast.Name)}
            identifier, scope = row['identifier_field'], row['scope_field']
            sequences = []
            for records, names in calls:
                if records and all(identifier in r and scope in r and isinstance(r[identifier], (str, int))
                                   and isinstance(r[scope], (str, int)) for r in records):
                    sequences.append(([(r[scope], r[identifier]) for r in records], names))
            observed = False
            if row['kind'] == 'shared-identifier':
                observed = any(a[1] == b[1] and a[0] != b[0] for seq, _ in sequences
                               for i, a in enumerate(seq) for b in seq[i + 1:])
                observed |= any(state_a and state_a == state_b and any(a[1] == b[1] and a[0] != b[0] for a in earlier for b in later)
                                for i, (earlier, state_a) in enumerate(sequences)
                                for later, state_b in sequences[i + 1:])
            elif row['kind'] == 'duplicate-before-new':
                observed = any(a in seq[:i] and any(b != a for b in seq[i + 1:])
                               for seq, _ in sequences for i, a in enumerate(seq))
            else:
                observed = (len(set(snapshots) & asserted) >= 2 and any(
                    state_a and state_a == state_b and any(r in earlier for r in later) and any(r not in earlier for r in later)
                    for i, (earlier, state_a) in enumerate(sequences) for later, state_b in sequences[i + 1:]))
            item['observation'] = 'shape-observed' if observed else 'shape-missing' if sequences else 'unknown'
        result.append(item)
    return result
