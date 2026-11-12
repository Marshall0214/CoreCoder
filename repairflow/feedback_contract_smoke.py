"""Three tiny local schema checks; no repair execution, Docker, or cloud API."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

from repairflow.feedback_actions import SCHEMA_ID, parse_action, schema
from repairflow.feedback_context import build_context
from repairflow.feedback_repair import usage
from repairflow.feedback_repair_v2 import SYSTEM
from repairflow.github_issue import NoRedirect
from repairflow.issue_providers import OllamaProvider
from repairflow.patch_validator import ROOT, inside, save


def run(output, *, model='qwen3.5:27b', timeout=240):
    output = inside(output)
    if not output.is_relative_to(ROOT / '.tmp') or type(timeout) is not int or timeout < 1:
        raise ValueError('Use a fresh project .tmp output and positive timeout')
    provider = OllamaProvider(model, time.monotonic() + timeout)
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'initializing', 'scope': 'synthetic action-format compatibility, not Issue repair',
              'model': model, 'thinking': False, 'schema_id': SCHEMA_ID, 'results': [],
              'fresh_model_calls': 0, 'cloud_api_calls': 0, 'independent_grading_used': False,
              'server_input_truncation': 'not_verified'}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        environment = {}
        for endpoint in ('version', 'tags', 'ps'):
            with opener.open('http://127.0.0.1:11434/api/' + endpoint, timeout=5) as response:
                environment[endpoint] = json.loads(response.read(1_000_001))
        installed = next((row for row in environment['tags'].get('models', []) if row['name'] == model), None)
        if installed is None:
            raise ValueError('Requested local model is not installed; no download was attempted')
        report.update(model_digest=installed['digest'], ollama_version=environment['version'].get('version'))
        save(output / 'environment.json', environment)
        action_schema = schema()
        save(output / 'action-schema.json', action_schema)
        examples = [('finish', {}), ('read_symbol', {'path': 'pkg/calc.py', 'symbol': 'total', 'offset': 0}),
                    ('apply_patch', {'workspace_revision': 2, 'edits': [
                        {'file': 'pkg/calc.py', 'old': 'return value', 'new': 'return value * 2'}]})]
        for number, (action, arguments) in enumerate(examples, 1):
            folder = output / f'case-{number:02d}'
            folder.mkdir()
            expected = {'action': action, 'arguments': arguments}
            task = {'instance_id': f'schema-smoke-{number}', 'repo': 'synthetic/contract', 'base_commit': 'a' * 40,
                    'problem_statement': 'Protocol compatibility check only. Copy this exact JSON action: ' + json.dumps(expected)}
            messages, context = build_context(
                system=SYSTEM + '\nAction JSON Schema:\n' + json.dumps(action_schema), task=task, guidance='',
                revision=2, readable=['pkg/calc.py'], editable=['pkg/calc.py'], remaining=20,
                fragments=[], feedback={'status': 'synthetic_format_check'}, actions=[], schema=action_schema)
            save(folder / 'messages.json', messages)
            save(folder / 'expected.json', expected)
            response = provider.chat(messages, tools=[], max_tokens=-1, response_schema=action_schema)
            (folder / 'response.txt').write_text(response.content, encoding='utf-8')
            parsed = parse_action(response.content)
            measured = usage(response)
            context['native_usage'] = measured
            save(folder / 'context.json', context)
            report['results'].append({'case': number, 'requested_action': action,
                                      'schema_valid': True, 'matches_requested': parsed == (action, arguments),
                                      'usage': measured})
            if parsed != (action, arguments):
                raise ValueError('Schema-valid action differs from the requested compatibility example')
        report['status'] = 'passed'
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        report['fresh_model_calls'] = len(provider.calls)
        report['provider_calls'] = provider.calls
        report['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
            ('repairflow/feedback_contract_smoke.py', 'repairflow/feedback_actions.py',
             'repairflow/feedback_context.py', 'repairflow/feedback_repair_v2.py', 'repairflow/issue_providers.py')}
        save(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='qwen3.5:27b')
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    report = run(args.output, model=args.model, timeout=args.timeout)
    print(json.dumps({key: report[key] for key in ('status', 'fresh_model_calls', 'results')}))
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
