"""Ollama zero flags and unrelated truncation must not become input warnings."""
import json
from pathlib import Path

import pytest

from evals.ollama_input_logs import classify


def test_real_slot_release_zero_flags_are_not_input_truncation_warnings():
    text = ('slot      release: id  0 | task 676 | stop processing: n_tokens = 2022, truncated = 0\n'
            'slot      release: id  0 | task 1541 | stop processing: n_tokens = 5070, truncated = 0\n')
    result = classify(text)
    assert result['server_input_truncation'] == 'not_verified'
    assert result['confirmed_input_truncation_warnings'] == []
    assert result['normal_zero_truncation_lines'] == text.splitlines()
    assert result['input_completeness_verified'] is False


def test_frozen_real_input_prompt_warnings_remain_positive():
    path = Path(__file__).resolve().parents[1] / 'docs/harness2_analysis_20261107/provider-truncation-excerpt.json'
    evidence = json.loads(path.read_text(encoding='utf-8'))
    lines = [row['text'] for row in evidence['samples']]
    result = classify('\n'.join(lines))
    assert result['confirmed_input_truncation_warnings'] == lines
    assert result['raw_truncation_related_lines'] == lines
    assert result['server_input_truncation'] == 'warning_observed'
    assert result['input_completeness_verified'] is False


@pytest.mark.parametrize('line', [
    'WARN msg="TRUNCATING   INPUT\tPROMPT" limit=65536 prompt=90000 keep=4 new=65536',
    'WARN input prompt was truncated to 65536 tokens',
    'WARN input was truncated from 90000 to 65536 tokens',
    'WARN prompt truncated from 90000 to 65536 tokens',
    'WARN truncated the input prompt from 90000 to 65536 tokens',
    'WARN input prompt truncation detected',
    'WARN input_truncated=true',
    'WARN "input_truncated": 12',
])
def test_explicit_input_truncation_variants_are_confirmed_without_rewriting_lines(line):
    result = classify(line)
    assert result['confirmed_input_truncation_warnings'] == [line]
    assert result['server_input_truncation'] == 'warning_observed'
    assert result['input_completeness_verified'] is False


@pytest.mark.parametrize('line', [
    'WARN output truncated after 100000 bytes',
    'WARN response was truncated',
    'INFO truncating stdout to 12000 characters',
    'WARN completion truncated by max_tokens',
])
def test_output_or_log_truncation_is_separate_from_input_evidence(line):
    result = classify(line)
    assert result['non_input_truncation_lines'] == [line]
    assert result['confirmed_input_truncation_warnings'] == []
    assert result['server_input_truncation'] == 'not_verified'


@pytest.mark.parametrize('line', [
    'slot release: id 0 | truncated = 1',
    'WARN truncation detected',
    'INFO input truncation disabled',
    'DEBUG not truncating input prompt',
    'DEBUG no longer truncating input prompt',
    'WARN truncating input prompt, truncated = 0',
])
def test_ambiguous_negated_or_contradictory_messages_do_not_confirm_truncation(line):
    result = classify(line)
    assert result['ambiguous_truncation_lines'] == [line]
    assert result['confirmed_input_truncation_warnings'] == []
    assert result['server_input_truncation'] == 'not_verified'


@pytest.mark.parametrize('line', [
    'slot release | TRUNCATED  =  0',
    'INFO "input_truncated": false, "tokens": 100',
    'INFO input_truncated=0',
])
def test_explicit_zero_or_false_flags_are_normal_without_proving_completeness(line):
    result = classify(line)
    assert result['normal_zero_truncation_lines'] == [line]
    assert result['server_input_truncation'] == 'not_verified'
    assert result['input_completeness_verified'] is False


def test_mixed_lines_keep_order_duplicates_and_all_categories():
    zero = 'slot release | truncated = 0'
    positive = 'WARN truncating input prompt limit=32 prompt=100'
    output = 'WARN output truncated'
    ambiguous = 'truncated = 1'
    result = classify(f'server ready\n{zero}\n{positive}\n{output}\n{ambiguous}\n{positive}')
    assert result['raw_truncation_related_lines'] == [zero, positive, output, ambiguous, positive]
    assert result['confirmed_input_truncation_warnings'] == [positive, positive]
    assert result['normal_zero_truncation_lines'] == [zero]
    assert result['non_input_truncation_lines'] == [output]
    assert result['ambiguous_truncation_lines'] == [ambiguous]


def test_absent_evidence_is_not_a_complete_input_claim():
    result = classify('server ready\nPOST /api/chat 200\n')
    assert result['raw_truncation_related_lines'] == []
    assert result['server_input_truncation'] == 'not_verified'
    assert result['input_completeness_verified'] is False
    with pytest.raises(TypeError):
        classify(b'truncating input prompt')
