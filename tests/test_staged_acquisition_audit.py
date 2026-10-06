import pytest

from docs.experiments.staged_acquisition_audit_v1 import definition, read_history, returned_lines


def events(offset, limit, response, start=1):
    return [{'event': 'tool_started', 'tool': 'read_file', 'sequence': start,
             'arguments': {'file_path': 'entry.py', 'offset': offset, 'limit': limit}},
            {'event': 'tool_finished', 'tool': 'read_file', 'sequence': start + 1, 'result': response}]


def test_request_range_and_duplicate_read_are_not_mistaken_for_tool_cap():
    trace = events(1, 2, '1\ta\n2\tb') + events(2, 1, '2\tb', 3)
    reads = read_history(trace, 'a\nb\nc\n', 'entry.py')
    assert reads[0]['returned_end'] == 2 and reads[0]['arguments']['limit'] == 2
    assert reads[1]['duplicate_lines'] == 1 and reads[1]['new_lines'] == 0


def test_footer_is_not_source_and_crlf_text_is_validated():
    assert returned_lines('1\ta\n2\tb\n[bounded read; next offset 3]', 'a\r\nb\r\n') == [1, 2]


@pytest.mark.parametrize('response', ['1\tforged', '1\ta\n3\tc'])
def test_truncated_forged_or_noncontiguous_lines_are_rejected(response):
    with pytest.raises(ValueError):
        returned_lines(response, 'a\nb\nc\n')


def test_definition_uses_ast_end_including_return_tail():
    assert definition('def prompt():\n    """doc"""\n    return 1\n', 'prompt') == {'start': 1, 'end': 3, 'lines': 3}


def test_unmatched_read_completion_is_rejected():
    with pytest.raises(ValueError, match='no request'):
        read_history([{'event': 'tool_finished', 'tool': 'read_file', 'result': '1\ta'}], 'a\n', 'entry.py')
