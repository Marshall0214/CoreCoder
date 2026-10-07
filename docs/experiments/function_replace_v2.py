"""Strict single-JSON envelope normalization; source and function rules stay v1."""
import json
import re

from docs.experiments import function_replace_v1 as base

SYSTEM = base.SYSTEM
guard = base.guard


def normalize(content):
    text = content.strip()
    match = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', text, re.DOTALL)
    return match[1].strip() if match else text


def lower(content, workspace, allowed, evidence):
    return base.lower(normalize(content), workspace, allowed, evidence)


def transact(content, workspace, allowed, evidence, output, python, imports):
    try:
        patch = lower(content, workspace, allowed, evidence)
    except (ValueError, TypeError, KeyError, SyntaxError, UnicodeError) as exc:
        result = {'accepted': False, 'committed': False, 'reason': 'invalid_patch', 'changed_files': [],
                  'original_unchanged': True, 'error': str(exc), 'protocol': 'function-replace-v2'}
        output.mkdir(parents=True, exist_ok=False)
        (output/'transaction.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result, None
    result = guard.transact(patch, workspace, allowed, evidence, output, python, imports)
    (output/'resolved-patch.json').write_text(patch, encoding='utf-8')
    return result, patch
