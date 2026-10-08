"""Derive independent diagnostic cases from public assertions; official checks unchanged."""
import ast
import copy
import json
import re
from pathlib import Path
from unittest.mock import patch

from docs.experiments import predicate_runtime_feedback_v1 as single
from evals.runner import digest, snapshot

previous, guarded, PROBE = single.previous, single.guarded, single.PROBE


def split_public(source):
    """Task-specific splitter; reuse public expressions and expectations verbatim in AST."""
    tree = ast.parse(source)
    provenance = []
    found = set()
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name not in ('Reproduce', 'Preserve'):
            continue
        if len(cls.body) != 1 or not isinstance(cls.body[0], ast.FunctionDef):
            raise ValueError('Unexpected public class shape')
        method = cls.body[0]
        assertions = [n for n in method.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                      and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'assertEqual'
                      and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == 'self']
        count = 5 if cls.name == 'Reproduce' else 2
        if len(assertions) != count:
            raise ValueError('Unexpected public assertion count')
        prefix = method.body[:method.body.index(assertions[0])]
        if method.body != prefix + assertions:
            raise ValueError('Unsupported interleaved public statements')
        if cls.name == 'Reproduce':
            # Keep the short locate call and its seen[-1] assertion together.
            if not (isinstance(assertions[2].value.args[0], ast.Subscript)
                    and isinstance(assertions[2].value.args[0].value, ast.Name)
                    and assertions[2].value.args[0].value.id == 'seen'):
                raise ValueError('Unexpected dependent public assertion')
            groups = ((0,), (1, 2), (3,), (4,))
        else:
            groups = ((0,), (1,))
        methods = []
        for number, indexes in enumerate(groups, 1):
            case = copy.deepcopy(method)
            case.name = method.name + '_case_' + str(number)
            case.body = copy.deepcopy(prefix + [assertions[i] for i in indexes])
            methods.append(case)
            provenance.append({'group': cls.name, 'method': case.name,
                               'original_assertion_lines': [assertions[i].lineno for i in indexes]})
        cls.body = methods
        found.add(cls.name)
    if found != {'Reproduce', 'Preserve'}:
        raise ValueError('Both public groups required')
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n', provenance


def observe(workspace, job, root):
    workspace, root = Path(workspace).resolve(), Path(root).resolve()
    original = Path(job['harness']).resolve()
    if digest(snapshot(original)) != job['harness_hash']:
        raise ValueError('Original public harness changed')
    root.mkdir()
    derived = root / 'derived-public'
    derived.mkdir()
    code, provenance = split_public((original / 'test_admission.py').read_text(encoding='utf-8'))
    (derived / 'test_admission.py').write_text(code, encoding='utf-8')
    derived_job = dict(job, harness=str(derived), harness_hash=digest(snapshot(derived)))
    # Ordinary execution and instrumented execution must agree on each case, not
    # merely on overall group success. Each case reinitializes its public setup.
    plain = previous.public_check(workspace, derived, job['package'], job['source_root'], root / 'plain')
    single.observe(workspace, derived_job, root / 'trace', {'public': plain})
    trace = json.loads((root / 'trace' / 'observation.json').read_text(encoding='utf-8'))
    if digest(snapshot(original)) != job['harness_hash']:
        raise ValueError('Original public harness changed')
    if not all(g['usable'] for g in trace['groups']):
        return None
    data = trace['payload']
    expected = {(r['group'], r['method']) for r in provenance}
    actual = {(r['group'], r['test'].rsplit('.', 1)[-1]) for r in data['records']}
    if expected != actual or len(data['records']) != len(expected):
        return None
    for group in ('Reproduce', 'Preserve'):
        text = (root / 'plain' / (group + '.stderr.txt')).read_text(encoding='utf-8', errors='replace')
        statuses = dict(re.findall(r'(?m)^(\w+) \([^\n]+\) \.\.\. (ok|FAIL|ERROR)$', text))
        for row in data['records']:
            if row['group'] == group:
                name = row['test'].rsplit('.', 1)[-1]
                if name not in statuses or (statuses[name] == 'ok') != row['passed']:
                    return None
            if row['passed']:
                # Retain all case outcomes; spend the fixed evidence budget on
                # failing inputs, rather than repeating successful call details.
                row.pop('operations', None)
    data['passing_operation_details_omitted'] = True
    data['source'] = 'Independent diagnostics derived from existing certified public assertions; not the official grader'
    data['scenario_provenance'] = provenance
    if len(json.dumps(data)) > 5000:
        return None
    return data


def run_candidate(llm, job, events):
    original = guarded.feedback

    def feedback(outcomes, workspace, job, root):
        result = original(outcomes, workspace, job, root)
        data = observe(workspace, job, root / 'independent-probe')
        if data is not None:
            result['public_runtime_observations'] = data
        previous.write_json(root / 'independent-observation.json', {'added': data is not None, 'payload': data})
        events.emit('independent_predicate_observation', added=data is not None)
        return result

    with patch.object(guarded, 'feedback', feedback):
        result = guarded.run_candidate(llm, job, events)
    result['protocol'] = 'independent-predicate-v1'
    return result
