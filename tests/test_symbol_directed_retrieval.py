import json
from pathlib import Path

import pytest

from docs.experiments import symbol_directed_repair_v1 as comparison
from docs.experiments import symbol_directed_retrieval_v1 as directed


def build(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    allowed = [name for name in files if name.startswith('src/')]
    index = directed.retrieval.FunctionIndex(root, allowed)
    index.refresh()
    return index, allowed


def names(index, ranked):
    return [index.names[directed.symbol_key(chunk)] for _, chunk in ranked]


def test_qualified_implementation_beats_keyword_heavy_caller(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'class HelpFormatter:\n    def write_usage(self):\n        return 1\n',
                               'src/b.py': 'def caller():\n    """HelpFormatter.write_usage usage args empty contract contracts"""\n    pass\n'})
    description = 'HelpFormatter.write_usage must handle empty args'
    assert names(index, index.rank(description))[0] == 'caller'
    ranked, metadata = directed.rank(index, description, description)
    assert names(index, ranked)[0] == 'HelpFormatter.write_usage'
    assert metadata['matches'][0]['resolution'] == 'resolved'
    packed = directed.retrieval.pack(index, ranked, top_k=1)
    assert directed.coverage(packed, metadata)['recall'] == 1


def test_class_context_disambiguates_bare_method(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'class One:\n    def validate(self):\n        return True\n',
                               'src/b.py': 'class Two:\n    def validate(self):\n        return False\n'})
    ranked, metadata = directed.rank(index, 'Two validate', 'Two: validate must handle input')
    assert names(index, ranked)[0] == 'Two.validate'
    assert metadata['matches'][0]['reason'] == 'class-scoped-bare'
    assert [r['symbol'] for r in metadata['resolved_symbols']] == ['Two.validate']


@pytest.mark.parametrize('description', ['validate must handle input', 'One.validate must work'])
def test_ambiguous_names_do_not_arbitrarily_choose_a_file(tmp_path, description):
    index, _ = build(tmp_path, {'src/a.py': 'class One:\n    def validate(self):\n        return True\n',
                               'src/b.py': 'class One:\n    def validate(self):\n        return False\n'})
    ranked, metadata = directed.rank(index, description, description)
    assert ranked == index.rank(description)
    assert metadata['matches'][0]['resolution'] == 'ambiguous'
    assert not metadata['resolved_symbols']


def test_module_qualification_resolves_same_class_names(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'class One:\n    def validate(self):\n        return True\n',
                               'src/b.py': 'class One:\n    def validate(self):\n        return False\n'})
    ranked, metadata = directed.rank(index, 'a.One.validate', 'a.One.validate must work')
    assert ranked[0][1].path == 'src/a.py'
    assert metadata['matches'][0]['resolution'] == 'resolved'


def test_unknown_name_falls_back_without_guessing_or_class_expansion(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'class One:\n    def __init__(self):\n        """salt contracts"""\n        pass\n'})
    description = 'One must preserve salt; Missing.fix and never_seen are mentioned'
    ranked, metadata = directed.rank(index, description, description)
    assert ranked == index.rank(description)
    assert not metadata['resolved_symbols']
    assert {r['identifier'] for r in metadata['matches']} == {'Missing.fix', 'never_seen'}
    assert directed.coverage(directed.retrieval.pack(index, ranked), metadata)['recall'] is None


def test_case_sensitive_identifier_and_repeated_mentions_are_deduplicated(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'def do_work():\n    return True\n'})
    ranked, metadata = directed.rank(index, 'do_work', 'do_work must call do_work, not DO_WORK')
    assert len(metadata['resolved_symbols']) == 1
    assert names(index, ranked) == ['do_work']
    assert next(r for r in metadata['matches'] if r['identifier'] == 'DO_WORK')['resolution'] == 'unresolved'


def test_ordinary_words_do_not_become_named_functions(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'def echo():\n    return 1\ndef output():\n    return 2\ndef argument():\n    return 3\n'})
    description = 'echo must preserve ordinary output and argument rendering'
    _, metadata = directed.rank(index, description, description)
    assert [r['symbol'] for r in metadata['resolved_symbols']] == ['echo']
    assert metadata['identifiers'] == ['echo']


@pytest.mark.parametrize('description', ['Call `echo` for output', 'Use echo() for output', 'echo and argument must work'])
def test_code_syntax_and_coordinated_requirement_subjects(description):
    mentions = directed.explicit_mentions(description)
    assert 'echo' in mentions
    assert 'output' not in mentions


def test_budget_skips_oversized_complete_function_without_truncation(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'def named_target():\n' + '    x = 1\n' * 100,
                               'src/b.py': 'def fallback():\n    """named_target"""\n    pass\n'})
    ranked, metadata = directed.rank(index, 'named_target', 'named_target')
    packed = directed.retrieval.pack(index, ranked, limit=100, top_k=1)
    assert packed['metadata']['evidence_chars'] <= 100
    assert packed['evidence'][0]['symbol'] == 'fallback'
    assert packed['evidence'][0]['complete_symbol']
    assert directed.coverage(packed, metadata)['covered'] == 0
    assert packed['metadata']['discarded'][0]['reason'] == 'budget'


def test_public_only_source_and_exact_crlf_citations(tmp_path):
    index, allowed = build(tmp_path, {'src/a.py': 'raise RuntimeError("never execute")\r\ndef named_target():\r\n    return 1\r\n',
                                    'private/score.py': 'def scoring_secret():\n    return 2\n'})
    case = {'task_id': 'case', 'before': tmp_path, 'before_hash': directed.repair.digest(directed.repair.snapshot(tmp_path)),
            'description': 'named_target must handle scoring_secret correctly', 'allowed_files': allowed}
    observed = directed.observe(case)
    assert 'scoring_secret' not in index.names.values()
    for packed in observed['policies'].values():
        assert all(row['path'] == 'src/a.py' for row in packed['evidence'])
        assert '\r\n' in packed['evidence'][0]['content']
        assert packed['metadata']['dependency_depth'] == 0


def test_source_mutation_rejected_before_worker_input(tmp_path, monkeypatch):
    _, allowed = build(tmp_path, {'src/a.py': 'def named_target():\n    return 1\n'})
    case = {'task_id': 'case', 'before': tmp_path, 'before_hash': directed.repair.digest(directed.repair.snapshot(tmp_path)),
            'description': 'named_target', 'allowed_files': allowed}
    original = directed.retrieval.pack

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / 'src/a.py').write_text('def named_target():\n    return 2\n')
        return result

    monkeypatch.setattr(directed.retrieval, 'pack', mutate)
    with pytest.raises(ValueError, match='version'):
        directed.observe(case)


def row(policy, accepted=True):
    return {'repeat': 1, 'task_id': 'case', 'policy': policy, 'accepted': accepted,
            'status': 'passed' if accepted else 'failed_verification', 'worker': {'metrics': None}, 'process': {'seconds': 1}}


def test_summary_keeps_incomplete_pairs_and_unknown_cost():
    summary = comparison.summarize([row(directed.POLICIES[0])])
    assert summary['pairs']['incomplete'] == 1
    assert summary[directed.POLICIES[0]]['budget_accounted_tokens'] is None
    with pytest.raises(ValueError, match='duplicate'):
        comparison.summarize([row(directed.POLICIES[0])] * 2)


@pytest.mark.parametrize('repeats', [0, 4, True])
def test_repeat_bounds_before_any_side_effect(tmp_path, repeats):
    with pytest.raises(ValueError, match='Repeat'):
        comparison.run(tmp_path / 'unused', repeats)
    assert not (tmp_path / 'unused').exists()


def test_paired_runner_uses_same_worker_and_public_inputs(tmp_path, monkeypatch):
    cases, grading = [], []
    for prefix in ('click-', 'itsdangerous-'):
        for number in range(3):
            name = f'{prefix}{number}'
            source = tmp_path / name
            for label, value in (('before', 1), ('after', 2)):
                (source / label).mkdir(parents=True)
                (source / label / 'sample.py').write_text(f'def sample():\n    return {value}\n', encoding='utf-8')
            checks = source / 'checks'
            checks.mkdir()
            (checks / 'private.py').write_text('SCORING_SECRET', encoding='utf-8')
            cases.append({'task_id': name, 'before': source / 'before', 'before_hash': comparison.repair.digest(
                comparison.repair.snapshot(source / 'before')), 'description': 'sample must return the expected value',
                'allowed_files': ['sample.py']})
            grading.append({'case': {'checks_hash': comparison.repair.digest(comparison.repair.snapshot(checks))},
                                'checks': checks, 'source_root': source, 'python': Path('unused'),
                                'after_hash': comparison.repair.digest(comparison.repair.snapshot(source / 'after'))})
    monkeypatch.setattr(comparison, 'prepare', lambda output: (cases, grading))
    monkeypatch.setattr(comparison.repair, 'check_identity', lambda config: None)
    output = tmp_path / 'output'

    def groups(workspace, *args):
        assert len(json.loads((output / 'observations.json').read_text())) == 6
        passed = workspace.name == 'after'
        return {'Target': {'passed': passed, 'assertion_failure': not passed, 'execution_error': False, 'timed_out': False},
                'Controls': {'passed': True}}

    monkeypatch.setattr(comparison.repair, 'checked_groups', groups)
    monkeypatch.setattr(comparison.second.admission, 'checked_groups', groups)
    jobs = {}

    def process(command, workspace, timeout, stdout, stderr, env):
        assert command[2] == 'docs.experiments.retrieved_function_repair_v1'
        job_path = Path(command[-1])
        job = json.loads(job_path.read_text())
        assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
        assert 'SCORING_SECRET' not in json.dumps(job)
        key = job_path.parent.parent.name
        jobs.setdefault(key, []).append(job['evidence'])
        assert (workspace / 'sample.py').read_text().endswith('return 1\n')
        (workspace / 'sample.py').write_text('def sample():\n    return 2\n', encoding='utf-8')
        (job_path.parent / 'worker-result.json').write_text(json.dumps({'status': 'completed', 'metrics': None}))
        return {'returncode': 0, 'timed_out': False, 'seconds': 1}

    def verify(case, source, checks, workspace, original, allowed, root, python, timeout):
        assert (checks / 'private.py').read_text() == 'SCORING_SECRET'
        # One regression fails despite completed patches; never equate generation with accepted repair.
        return {'passed': not (source.name == 'click-0' and root.name == directed.POLICIES[1])}

    monkeypatch.setattr(comparison, 'run_process', process)
    monkeypatch.setattr(comparison.repair, 'verify', verify)
    monkeypatch.setattr(comparison.second, 'verify', verify)
    comparison.run(output)
    report = json.loads((output / 'experiment.json').read_text())
    assert report['complete'] and len(report['runs']) == 12
    assert all(len(values) == 2 and values[0] == values[1] for values in jobs.values())
    assert report['summary']['pairs']['baseline_only'] == 1
    assert report['summary']['pairs']['both_passed'] == 5
    assert report['protocol']['benchmark_eligible'] is False
    with pytest.raises(ValueError, match='fresh'):
        # Restore real prepare's earliest output guard without reading local admissions.
        monkeypatch.undo()
        comparison.prepare(output)
