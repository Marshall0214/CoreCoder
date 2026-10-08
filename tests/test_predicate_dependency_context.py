import hashlib
from types import SimpleNamespace

import pytest

from docs.experiments import predicate_dependency_context_v1 as context
from evals.runner import digest, snapshot
from evals.runtime import Events


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'workspace'
    package = root / 'more_itertools'
    package.mkdir(parents=True)
    (package / 'more.py').write_text('''def replace(items):
    return windowed(items)

def locate(items):
    return windowed(items)

def windowed(items):
    """Original window contract."""
    return items

def unrelated():
    return 'noise'
''', encoding='utf-8')
    (package / 'recipes.py').write_text('''_marker = object()

def consume(iterator, n=None):
    """Advance an iterator."""
    return next(iterator, None)
''', encoding='utf-8')
    allowed = ['more_itertools/more.py', 'more_itertools/recipes.py']
    return root, allowed


def test_dependency_spans_match_original_source_without_mutation(source):
    root, allowed = source
    original = digest(snapshot(root))
    rows = context.dependency_evidence(root, allowed)
    assert [r['symbol'] for r in rows] == ['replace', 'locate', 'windowed', 'consume', '_marker']
    assert 'Original window contract' in rows[2]['content']
    assert 'Advance an iterator' not in rows[3]['content'] and not rows[3]['complete_symbol']
    assert all('unrelated' not in r['content'] for r in rows)
    assert digest(snapshot(root)) == original
    context.previous.repair.validate_evidence(root, allowed, rows)


def test_large_window_docstring_is_replaced_by_cited_executable_body(source):
    root, allowed = source
    path = root / allowed[0]
    path.write_text(path.read_text().replace('Original window contract.', 'x' * 6000), encoding='utf-8')
    rows = context.dependency_evidence(root, allowed)
    assert rows[2]['content'].splitlines() == ['    return items'] and not rows[2]['complete_symbol']
    assert sum(len(r['content']) for r in rows) <= 6000


def test_oversized_target_source_never_expands_the_budget(source):
    root, allowed = source
    path = root / allowed[0]
    path.write_text(path.read_text().replace('def replace(items):', 'def replace(items):\n    """' + 'x' * 6100 + '"""'),
                    encoding='utf-8')
    with pytest.raises(ValueError, match='budget'):
        context.dependency_evidence(root, allowed)


def test_changed_source_invalidates_old_spans_and_refreshes_hash(source):
    root, allowed = source
    old = context.dependency_evidence(root, allowed)
    path = root / allowed[0]
    path.write_text(path.read_text().replace('return windowed(items)', 'return list(items)'), encoding='utf-8')
    with pytest.raises(ValueError, match='version'):
        context.previous.repair.validate_evidence(root, allowed, old)
    new = context.dependency_evidence(root, allowed)
    assert new[0]['content_hash'] != old[0]['content_hash']
    assert 'return list(items)' in new[0]['content']


def test_unallowed_dependency_is_rejected(source):
    root, allowed = source
    with pytest.raises(ValueError, match='allowed'):
        context.dependency_evidence(root, allowed[:1])


def test_ambiguous_dependency_is_rejected(source):
    root, allowed = source
    path = root / allowed[0]
    path.write_text(path.read_text() + '\ndef windowed(items):\n    return []\n', encoding='utf-8')
    with pytest.raises(ValueError, match='ambiguous'):
        context.dependency_evidence(root, allowed)


def test_feedback_keeps_dependencies_cited_to_the_current_candidate(source, monkeypatch):
    root, allowed = source
    job = {'workspace': str(root), 'allowed_files': allowed, 'description': 'public defect',
           'description_hash': hashlib.sha256(b'public defect').hexdigest(),
           'original_hash': digest(snapshot(root)), 'evidence': context.dependency_evidence(root, allowed)}
    for name in ('harness', 'frozen_harness'):
        path = root.parent / name
        path.mkdir()
        (path / 'test_admission.py').write_text('public checks', encoding='utf-8')
        job[name], job[name + '_hash'] = str(path), digest(snapshot(path))
    seen = []
    llm = SimpleNamespace(metrics=lambda: {'llm_calls': len(seen)})
    def request(shared, workspace, job, evidence, target, stage, feedback=None):
        assert shared is llm
        context.previous.repair.validate_evidence(workspace, allowed, evidence)
        assert [r['symbol'] for r in evidence] == ['replace', 'locate', 'windowed', 'consume', '_marker']
        seen.append(evidence)
        if stage == 'initial':
            path = workspace / allowed[0]
            path.write_text(path.read_text().replace('return windowed(items)', 'return list(items)'), encoding='utf-8')
        return {'status': 'completed'}
    monkeypatch.setattr(context.previous, 'request', request)
    def checked(workspace, job, target, stage):
        return {label: {group: {'passed': stage == 'corrected', 'timed_out': False, 'tests_run': 1, 'skipped': 0}
                        for group in ('Reproduce', 'Preserve')} for label in ('public', 'frozen')}
    monkeypatch.setattr(context.guarded, 'checked', checked)
    monkeypatch.setattr(context.guarded, 'feedback', lambda *args: {'test_code': 'public checks'})
    result = context.expanded_candidate(llm, job, Events(root.parent / 'trace.jsonl', 'test'))
    assert result['published'] and result['correction_retained'] and len(seen) == 2
    assert seen[0][0]['content_hash'] != seen[1][0]['content_hash']
