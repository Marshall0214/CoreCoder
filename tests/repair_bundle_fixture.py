"""Small self-contained bundle exercising the real engine without external models."""
import hashlib
import json

from docs.experiments.constrained_patch_v1 import previous
from docs.experiments.coverage_context_v2 import retrieve
from repairflow.bundles import tree_hash, write


def bundle(root, bad=False):
    root.mkdir(parents=True)
    source = root / 'source/src/pkg'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('def f(x):\n    return x + 1\n\ndef g(x):\n    return x\n', encoding='utf-8')
    description = 'f must return x plus two. Preserve g behavior.'
    allowed = ['src/pkg/__init__.py']
    for directory, target, control in [('public', 'Reproduce', 'Preserve'), ('frozen', 'Reproduce', 'Preserve'),
                                        ('grader', 'Target', 'Controls')]:
        path = root / directory
        path.mkdir()
        (path / 'test_admission.py').write_text(
            f'import unittest\nfrom pkg import f, g\nclass {target}(unittest.TestCase):\n'
            '    def test_target(self):\n        self.assertEqual(f(1), 3)\n'
            f'class {control}(unittest.TestCase):\n    def test_control(self):\n        self.assertEqual(g(0), 0)\n',
            encoding='utf-8')
    evidence = retrieve(root / 'source', allowed, description,
                        (root / 'public/test_admission.py').read_text(encoding='utf-8'))['evidence']
    system = previous.repair.patcher.SYMBOL_SYSTEM + ' Return a nonempty edits array that changes source. Identical old/new text is invalid. Use only exact supplied anchors; do not modify tests or bypass verification.'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(
        {'description': description, 'allowed_files': allowed, 'fragments': evidence}, ensure_ascii=False)}]
    content = json.dumps({'edits': [{'file': allowed[0], 'old': '    return x + 1',
                                    'new': '    return x + ' + ('4' if bad else '2')}]})
    write(root / 'replay.json', {'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
                               'content': content, 'call': {'finish_reason': 'stop', 'model_returned': 'deepseek-flash',
                                                           'prompt_tokens': 100, 'completion_tokens': 100}})
    data = {'schema_version': 1, 'strategy': 'coverage-v2-constrained-v1', 'task_id': root.name, 'repo': 'test/pkg',
            'package': 'pkg', 'source_root': 'src', 'description': description, 'allowed_files': allowed,
            'description_hash': hashlib.sha256(description.encode()).hexdigest(),
            'hashes': {name: tree_hash(root / name) for name in ('source', 'public', 'frozen', 'grader')},
            'replay_sha256': hashlib.sha256((root / 'replay.json').read_bytes()).hexdigest()}
    write(root / 'bundle.json', data)
    return root
