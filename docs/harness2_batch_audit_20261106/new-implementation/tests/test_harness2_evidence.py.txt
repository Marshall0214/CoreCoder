"""Large reflection records must remain readable, reversible and bounded."""
import json
import unittest

from integrations.harness2_evidence import pack, pack_nested, unpack


class EvidenceTests(unittest.TestCase):
    def test_sharing_preserves_exact_quotes_unicode_whitespace_and_aliases(self):
        text='def f():\n    return "中文\\path"\n'*200
        items={'a.md':'[OBSERVATION] '+json.dumps({'content':text}),
               'b.md':'[OBSERVATION] '+json.dumps({'content':text,'offset':1}),
               'alias.md':{'same_verbatim_content_as':'a.md'}}
        value=pack(items)
        self.assertEqual(unpack(value),items)
        self.assertEqual(len(value['shared_verbatim_text']),1)
        self.assertLess(len(json.dumps(value)),len(json.dumps(items)))

    def test_large_unique_evidence_is_rejected_not_truncated(self):
        with self.assertRaises(ValueError):
            pack({'a.md':'x'*160001})

    def test_reference_like_user_text_remains_literal(self):
        source={'a.md':'{"verbatim_text_ref":"fake"}','b.md':'plain text'}
        self.assertEqual(unpack(pack(source)),source)

    def test_nested_public_result_objects_are_shared_without_changing_any_character(self):
        checks = {'public_checks': {'Reproduce': {'stderr_tail': 'AssertionError: expected behavior\n' * 100},
                                  'Preserve': {'passed': True}}, 'errors': ['no patch']}
        source = {'rollout.md': '\n'.join('[PUBLIC] ' + json.dumps({**checks, 'round': i}) for i in range(80))}
        packed = pack(source)
        self.assertEqual(unpack(packed), source)
        self.assertLess(len(json.dumps(packed, ensure_ascii=False)), 160000)
        # Direct nested encoding also preserves literal strings resembling its own reference syntax.
        source['literal.md'] = '{"verbatim_text_ref":"nested-0"}\\n 中文'
        self.assertEqual(unpack(pack_nested(source)), source)

    def test_recursive_reference_cycles_are_rejected(self):
        body = {'verbatim_segments': [{'verbatim_text_ref': 'a'}]}
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            unpack({'shared_verbatim_text': {'a': body}, 'files': {'x': body}})
