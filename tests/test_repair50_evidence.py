"""Offline consistency guards; no model, project code or grading is executed."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / 'docs' / 'repair50_evidence'
spec = importlib.util.spec_from_file_location('repair50_audit', PACKET / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def reports():
    return tuple(json.loads((PACKET / 'inputs' / name).read_text(encoding='utf-8')) for name in audit.FILES)


def test_historical_totals_and_pairing(reports):
    baseline, candidate, manifest = reports
    result = audit.compare(manifest, baseline, candidate)
    assert result['before']['passed'] == 43
    assert result['after']['passed'] == 47
    assert len(result['gained']) == 5
    assert result['lost'] == ['more-negative-range-slice']
    assert result['before']['tokens'] == 715766
    assert result['after']['tokens'] == 648593
    assert result['token_change_percent'] == -9.38
    assert result['admission_target_outcomes'] == {'with_assertion_failures': 32, 'with_errors': 18}


@pytest.mark.parametrize('mutation,match', [
    ('acceptance', 'Acceptance predicate'),
    ('usage', 'Invalid provider usage'),
    ('duplicate', 'Missing, duplicate'),
    ('config', 'configuration changed'),
    ('admission', 'Admission evidence invalid'),
    ('test_flag', 'Test flag disagrees'),
])
def test_inconsistent_evidence_is_rejected(reports, mutation, match):
    baseline, candidate, manifest = reports
    row = candidate['runs'][0]
    if mutation == 'acceptance':
        row['accepted'] = not row['accepted']
    elif mutation == 'usage':
        row['worker']['provider_calls'][0]['total_tokens'] += 1
    elif mutation == 'duplicate':
        candidate['runs'][-1] = copy.deepcopy(row)
    elif mutation == 'config':
        candidate['protocol']['config']['token_budget'] += 1
    elif mutation == 'admission':
        manifest['cases'][0]['admission']['after']['Target']['returncode'] = 1
    else:
        row['verification']['groups']['Target']['passed'] = False
    with pytest.raises(ValueError, match=match):
        audit.compare(manifest, baseline, candidate)


def test_excerpt_tamper_is_rejected(tmp_path):
    (tmp_path / 'cases').mkdir()
    (tmp_path / 'cases' / 'index.json').write_text(json.dumps({'files': [
        {'file': 'cases/log.txt', 'sha256': '0' * 64}]}), encoding='utf-8')
    (tmp_path / 'cases' / 'log.txt').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='Excerpt changed'):
        audit.verify_excerpts(tmp_path)


def test_packet_audit_runs_without_installed_dependencies(tmp_path):
    output = tmp_path / 'offline-audit'
    result = subprocess.run([sys.executable, '-B', '-S', str(PACKET / 'audit.py'), '--output', str(output)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert summary['after']['passed'] == 47
    assert summary['excerpts_verified'] == 50
    second = subprocess.run([sys.executable, '-B', '-S', str(PACKET / 'audit.py'), '--output', str(output)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert second.returncode != 0
    assert 'fresh output' in second.stderr
