"""Large reflection records must remain readable, reversible and bounded."""
import json
import unittest

from integrations.harness2_evidence import pack, unpack


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
