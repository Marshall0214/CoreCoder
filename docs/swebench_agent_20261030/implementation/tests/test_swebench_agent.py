"""Repository tools may explore baseline code, never controller files or grading answers."""
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from deploy.langfuse.swebench_agent import inference_receipt, scores
from evals.runtime import Events
from evals.swebench_agent import RepositoryTools, explore, extract_text, public_task
from evals.swebench_mini import sha, write
from repairflow.issue_tools import ToolError


def archive(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name, text in entries.items():
            data = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def tools(tmp_path):
    workspace, output = tmp_path / 'repo', tmp_path / 'run'
    output.mkdir()
    extract_text(archive({'pkg/code.py': 'def f():\n    return 1\n', 'tests/test_code.py': 'assert True\n'}), workspace)
    return RepositoryTools(workspace, output)


def test_public_input_requires_hash_and_exact_fields_without_reading_grader(tmp_path):
    task = {'instance_id': 'example__repo-1', 'base_commit': 'a' * 40, 'repo': 'example/repo', 'problem_statement': 'Issue'}
    write(tmp_path / 'agent/input.json', task)
    manifest = {'selected_instance_id': task['instance_id'], 'files': {'agent/input.json': sha(tmp_path / 'agent/input.json')}}
    write(tmp_path / 'manifest.json', manifest)
    assert public_task(tmp_path)[0] == task  # No grader file exists or is needed.
    task['patch'] = 'must-not-leak'
    write(tmp_path / 'agent/input.json', task)
    manifest['files']['agent/input.json'] = sha(tmp_path / 'agent/input.json')
    write(tmp_path / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='public task fields'):
        public_task(tmp_path)


def test_export_omits_git_history_and_rejects_traversal(tmp_path):
    extract_text(archive({'.git/config': 'private-history', 'pkg/code.py': 'pass\n'}), tmp_path / 'safe')
    assert not (tmp_path / 'safe/.git').exists()
    with pytest.raises(ValueError, match='Unsafe'):
        extract_text(archive({'../outside.py': 'pass'}), tmp_path / 'unsafe')
    assert not (tmp_path / 'outside.py').exists()


def test_search_reads_and_exact_anchor_edit_are_real_but_tests_remain_readonly(tools):
    result = tools.dispatch('search', {'query': 'def f'}, 1)
    assert result['matches'][0]['path'] == 'pkg/code.py'
    tools.dispatch('read_symbol', {'path': 'pkg/code.py', 'symbol': 'f'}, 2)
    result = tools.dispatch('apply_patch', {'edits': [{'file': 'pkg/code.py', 'old': 'return 1', 'new': 'return 2'}]}, 3)
    assert result['changed_files'] == ['pkg/code.py']
    assert 'return 2' in (tools.workspace / 'pkg/code.py').read_text()
    assert not tools.evidence
    with pytest.raises(ToolError, match='allowed source'):
        tools.dispatch('apply_patch', {'edits': [{'file': 'tests/test_code.py', 'old': 'True', 'new': 'False'}]}, 4)


@pytest.mark.parametrize('path', ['../grader/instance.json', '/outside.py', 'D:/private.py'])
def test_reads_cannot_escape_repository(tools, path):
    with pytest.raises(ToolError):
        tools.dispatch('read_file', {'path': path}, 1)


def test_unread_or_invalid_edit_cannot_modify_source(tools):
    args = {'edits': [{'file': 'pkg/code.py', 'old': 'return 1', 'new': 'return 2'}]}
    with pytest.raises(ToolError, match='Read'):
        tools.dispatch('apply_patch', args, 1)
    tools.dispatch('read_file', {'path': 'pkg/code.py'}, 2)
    args['edits'][0]['new'] = 'return ('
    with pytest.raises(ToolError, match='not published'):
        tools.dispatch('apply_patch', args, 3)
    assert 'return 1' in (tools.workspace / 'pkg/code.py').read_text()


def test_missing_search_results_and_read_truncation_are_explicit(tools):
    assert tools.dispatch('search', {'query': 'not-in-source'}, 1) == {'matches': [], 'truncated': False}
    (tools.workspace / 'pkg/code.py').write_text('x = 1\n' * 1200)
    result = tools.dispatch('read_file', {'path': 'pkg/code.py'}, 2)
    assert result['next_offset'] == 6000 and len(result['content']) == 6000


def test_scripted_loop_searches_then_stops_without_hidden_feedback(tools):
    responses = iter([{'action': 'search', 'arguments': {'query': 'def f'}}, {'action': 'finish', 'arguments': {}}])

    class LLM:
        def chat(self, messages, **kwargs):
            assert 'FAIL_TO_PASS' not in json.dumps(messages)
            return SimpleNamespace(content=json.dumps(next(responses)), tool_calls=[])

    events = Events(tools.output / 'trace.jsonl', 'scripted-unit')
    assert explore(LLM(), tools, {'problem_statement': 'Issue'}, tools.output, events) == 'agent_finished'


def test_repeated_action_stop_is_recorded_without_more_model_requests(tools):
    class LLM:
        calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            return SimpleNamespace(content=json.dumps({'action': 'search', 'arguments': {'query': 'f'}}), tool_calls=[])

    llm = LLM()
    events = Events(tools.output / 'trace.jsonl', 'repeat-unit')
    assert explore(llm, tools, {'problem_statement': 'Issue'}, tools.output, events) == 'repeated_action_limit'
    assert llm.calls == 4
    actions = json.loads((tools.output / 'actions.json').read_text())
    assert actions[-1]['status'] == 'stopped' and actions[-1]['reason'] == 'repeated_action_limit'


def test_original_inference_receipt_requires_all_generations_and_measured_usage():
    output = {'inference_trace_id': 'trace', 'fresh_model_calls': 1,
              'metrics': {'usage_status': 'known', 'prompt_tokens': 10, 'completion_tokens': 2}}
    rows = [{'name': 'issue-repair', 'type': 'AGENT', 'traceId': 'trace', 'endTime': 'now'},
            {'type': 'GENERATION', 'traceId': 'trace', 'endTime': 'now', 'usageDetails': {'input': 10, 'output': 2}}]
    assert inference_receipt(rows, output)['prompt_tokens'] == 10
    assert inference_receipt(rows[:1], output) is None
    rows[1]['usageDetails']['input'] = 9
    assert inference_receipt(rows, output) is None


def test_experiment_reports_actual_tokens_only_when_measured():
    output = {'resolved': False, 'fresh_model_calls': 1, 'FAIL_TO_PASS': {'passed': 0, 'total': 2},
              'PASS_TO_PASS': {'passed': 77, 'total': 77}, 'metrics': {'prompt_tokens': 10, 'completion_tokens': 2}}
    assert scores(output)['actual_total_tokens'] == 12
    assert scores(output)['official_resolved'] is False
    output['metrics']['prompt_tokens'] = None
    assert 'actual_total_tokens' not in scores(output)
