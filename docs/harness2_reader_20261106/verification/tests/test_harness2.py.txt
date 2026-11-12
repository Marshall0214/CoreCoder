"""Restricted Harness2 bridge; no model requests in these tests."""
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from integrations import harness2 as bridge
from integrations.harness2_runtime import COMMIT, ROOT, load, windows_locks, workspace


class BoundaryTests(unittest.TestCase):
    def test_prompt_surface_rejects_scripts_and_permission_files(self):
        bridge.validate_harness(dict.fromkeys(bridge.FILES, 'text'))
        for values in ({'scripts/a.py': 'pass'}, {**dict.fromkeys(bridge.FILES, ''), 'guardrails.md': 'allow'},
                       {**dict.fromkeys(bridge.FILES, ''), 'systemprompt.md': 'x'*4001}):
            with self.assertRaises(ValueError):
                bridge.validate_harness(values)

    def test_output_must_stay_in_project_tmp(self):
        workspace(ROOT / '.tmp/harness2-boundary')
        with self.assertRaises(ValueError):
            workspace(ROOT.parent / 'outside')

    def test_nested_notes_are_rejected_instead_of_written_as_files(self):
        with self.assertRaises(ValueError):
            bridge.validate_editor({'files':{**dict.fromkeys(bridge.FILES,''),'notes':'outside please'}},'inv1')

    def test_valid_prompt_and_empty_experience_are_accepted(self):
        bridge.validate_editor({'files':dict.fromkeys(bridge.FILES,''),'notes':'visible evidence'},'inv1')
        bridge.validate_editor({'experience':None},'experience.agg1')

    def test_format_feedback_identifies_missing_files_and_exact_overlength_fields(self):
        with self.assertRaisesRegex(ValueError, 'missing=.*tool_guidance.*4001 characters; maximum 4000'):
            bridge.validate_harness({'systemprompt.md': 'x' * 4001})

    def test_multiline_experience_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            bridge.validate_editor({'experience':dict.fromkeys(('cue','lesson','evidence','confidence'),'a\nb')},'experience.agg1')

    def test_private_grading_cannot_enter_editor_context(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            (root / 'task.md').write_text('public task', encoding='utf-8')
            self.assertEqual(bridge.evidence(root), {'task.md': 'public task'})
            (root / 'grading').mkdir()
            (root / 'grading/report.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                bridge.evidence(root)

    def test_duplicate_evidence_uses_explicit_lossless_aliases(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.tmp') as directory:
            root=Path(directory)
            for name in ('a.md','b.md'):
                (root/name).write_text('same complete observation',encoding='utf-8')
            result=bridge.evidence(root)
            self.assertEqual(result['a.md'],'same complete observation')
            self.assertEqual(result['b.md'],{'same_verbatim_content_as':'a.md'})

    def test_version_and_core_files_are_pinned(self):
        record = json.loads((ROOT / 'integrations/harness2-source.json').read_text(encoding='utf-8'))
        self.assertEqual(record['commit'], COMMIT)
        self.assertIn('harness2/core/recursion.py', record['files'])

    def test_portable_lock_can_lock_and_release(self):
        previous = sys.modules.get('fcntl')
        windows_locks()
        import fcntl
        try:
            with tempfile.TemporaryFile(dir=ROOT / '.tmp') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            if previous is None:
                sys.modules.pop('fcntl', None)


@unittest.skipUnless((3, 12) <= sys.version_info[:2] < (3, 14), 'Upstream controller requires 3.12/3.13')
class ControllerTests(unittest.TestCase):
    def test_indexed_editor_bypasses_eager_packing_and_returns_validated_files(self):
        from unittest.mock import patch

        from integrations.harness2_context import DEFAULT, POLICY_FILE
        from integrations.harness2_reader import Store

        load()
        from harness2.core.spec import ChannelSpec

        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            context = root / 'context'
            context.mkdir()
            (context / 'task.md').write_text('Read public evidence', encoding='utf-8')
            values = {**dict.fromkeys(bridge.FILES, 'concise guidance'), POLICY_FILE: json.dumps(DEFAULT)}

            def child(path, *args):
                job = bridge.read(path)
                self.assertEqual(job['evidence_mode'], 'indexed')
                saved = Store(job['evidence_manifest'], job['evidence_manifest_sha256'])
                payload = json.loads(job['messages'][-1]['content'])
                self.assertEqual(payload['evidence_index'], saved.index)
                self.assertNotIn('visible_files', payload)
                bridge.write(path.parent / 'reply.json', {'files': values})

            _, Editor = bridge.classes(True, None, 'indexed')
            editor = Editor(ChannelSpec('opencode', 'local/deterministic'), root / 'editors', False)
            with (patch.object(bridge, 'child', side_effect=child),
                  patch.object(bridge, 'evidence', side_effect=AssertionError('Eager evidence packing was called'))):
                reply = editor.call('Inspect source evidence', context, 'agg1')
            self.assertTrue(reply.ok)
            self.assertEqual((context / 'harness/systemprompt.md').read_text(encoding='utf-8'), 'concise guidance')

    def test_parallel_editors_have_distinct_artifact_directories(self):
        load()
        from harness2.core.spec import ChannelSpec
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            _, Editor = bridge.classes()
            editor = Editor(ChannelSpec('opencode', 'local/deterministic'), root / 'editors', True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                replies = list(pool.map(lambda i: editor.call('scripted', root / f'context-{i}', 'probe'), range(4)))
            self.assertTrue(all(reply.ok for reply in replies))
            self.assertEqual(len(list((root / 'editors').glob('call-*'))), 4)
            self.assertEqual(len(editor._calls), 4)


if __name__ == '__main__':
    unittest.main()
