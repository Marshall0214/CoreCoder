"""Optional upstream integration: no inference, network or Docker in these tests."""
import io
import json
import os
import time
from types import SimpleNamespace

import pytest

from evals import mini_swe
from evals import mini_swe_adapter as adapter
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig
from repairflow.issue_providers import ProviderFailure, UsageResponse


@pytest.fixture
def upstream(tmp_path):
    adapter.configure(tmp_path / 'mini-state')
    pytest.importorskip('minisweagent', reason='Optional mini-swe-agent API dependencies')
    return mini_swe.upstream()[:2]


def test_original_loop_executes_actions_and_keeps_history(upstream, tmp_path, monkeypatch):
    Agent, settings = upstream
    replies = iter(['missing action', '```mswea_bash_command\nprintf evidence\n```',
                    '```mswea_bash_command\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```'])
    history = []

    def chat(messages, **kwargs):
        history.append(messages)
        return UsageResponse(content=next(replies), reported_usage={'prompt_tokens': 100, 'completion_tokens': 30})

    events = Events(tmp_path / 'trace.jsonl', 'scripted-mini')
    llm = BudgetLLM(SimpleNamespace(chat=chat, model='offline-scripted'),
                    RunConfig(mode='live', max_rounds=5, max_output_tokens=2048), events)
    model = adapter.MiniModel(llm, settings['model'], tmp_path, events)
    env = object.__new__(adapter.MiniEnvironment)
    env.output, env.events, env.deadline, env.steps, env.name, env.policy = tmp_path, events, time.monotonic() + 20, 0, 'fake', {}
    commands = []

    def bounded(args, timeout, limit):
        commands.append(args[-1])
        return 0, (b'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n' if len(commands) == 2 else b'evidence'), b'', False, False

    monkeypatch.setattr(adapter.runner, 'bounded', bounded)
    agent = Agent(model, env, **{**settings['agent'], 'step_limit': 5, 'output_path': tmp_path / 'trajectory.json'})
    assert agent.run('Fix a test issue')['exit_status'] == 'Submitted'
    assert commands == ['printf evidence', 'echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT']
    assert llm.calls == 3 and llm.metrics()['prompt_tokens'] == 300
    assert 'Format error' in history[1][-1]['content']
    assert 'evidence' in history[2][-1]['content']
    assert [row['role'] for row in history[2]][-2:] == ['assistant', 'user']
    assert json.loads((tmp_path / 'trajectory.json').read_text())['info']['mini_version'] == mini_swe.VERSION


@pytest.mark.parametrize('failure', [False, True])
def test_native_text_request_disables_thinking_and_keeps_usage(monkeypatch, failure):
    payload = {'done': True, 'done_reason': 'length' if failure else 'stop', 'message': {'content': 'text'},
               'prompt_eval_count': 42, 'eval_count': 10}
    requests = []

    def open_request(request, **kwargs):
        requests.append(request)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(adapter.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=open_request))
    provider = adapter.TextOllamaProvider('qwen3.5:27b', time.monotonic() + 20)
    if failure:
        with pytest.raises(ProviderFailure, match='incomplete_model_response') as exc:
            provider.chat([{'role': 'user', 'content': 'test'}])
        assert exc.value.reported_usage == {'prompt_tokens': 42, 'completion_tokens': 10}
    else:
        result = provider.chat([{'role': 'user', 'content': 'test'}])
        assert result.content == 'text' and result.reported_usage['prompt_tokens'] == 42
    sent = json.loads(requests[0].data)
    assert sent['think'] is False and 'format' not in sent and 'tools' not in sent
    assert requests[0].full_url == 'http://127.0.0.1:11434/api/chat'
    assert provider.calls[0]['usage_known']


def test_sandbox_command_has_no_writable_host_mounts(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(adapter.runner, 'control', lambda args, **kwargs: commands.append(args))
    env = adapter.MiniEnvironment(tmp_path, tmp_path, {'image_id': 'sha256:fake'}, None, time.monotonic() + 30)
    args = commands[0]
    assert args[args.index('--network') + 1] == 'none'
    assert args[args.index('--user') + 1] == '10001:10001'
    assert '--read-only' in args and '--cap-drop' in args and 'ALL' in args
    assert 'PYTHONPATH=/workspace/src:/workspace' in args and 'HOME=/tmp' in args
    assert args.count('--mount') == 1 and args[args.index('--mount') + 1].endswith(',target=/seed,readonly')
    assert args[args.index('--pull') + 1] == 'never'
    env.close()
    assert commands[-1] == ['rm', '-f', env.name]


def test_command_timeout_stops_agent_instead_of_retrying(upstream, monkeypatch, tmp_path):
    from minisweagent.exceptions import InterruptAgentFlow

    env = object.__new__(adapter.MiniEnvironment)
    env.output, env.events, env.deadline, env.steps, env.name = tmp_path, Events(tmp_path / 'trace', 'id'), time.monotonic()+10, 0, 'fake'
    monkeypatch.setattr(adapter.runner, 'bounded', lambda *args: (-1, b'', b'', True, False))
    with pytest.raises(InterruptAgentFlow) as exc:
        env.execute({'command': 'sleep 500'})
    assert exc.value.messages[0]['extra']['exit_status'] == 'command_timeout'


def test_deleted_baseline_is_unresolved_without_grading(monkeypatch, tmp_path):
    (tmp_path / 'agent').mkdir()
    (tmp_path / 'agent/report.json').write_text(json.dumps({'deleted_baseline_files': ['source.py']}))
    monkeypatch.setattr(mini_swe.local50, 'grade', lambda *args: pytest.fail('Deleted files cannot reach scoring'))
    assert mini_swe.grade({}, tmp_path)['resolved'] is False


def test_api_credentials_removed_from_worker_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'do-not-forward')
    env = mini_swe.mini_environment(tmp_path, 'agent')
    assert 'DEEPSEEK_API_KEY' not in env
    assert env['MSWEA_GLOBAL_CONFIG_DIR'].startswith(str(mini_swe.ROOT / '.tmp'))
    assert env['PYTHONPATH'].split(';' if adapter.os.name == 'nt' else ':')[0].endswith('mini-swe-deps')


@pytest.mark.skipif(os.environ.get('CORECODER_MINI_DOCKER_TEST') != '1', reason='Explicit real Docker acceptance')
def test_real_upstream_loop_edits_isolated_workspace_without_model(upstream, tmp_path):
    Agent, settings = upstream
    seed, output = tmp_path / 'seed', tmp_path / 'artifacts'
    seed.mkdir()
    output.mkdir()
    (seed / 'demo.py').write_text('value = 1\n', encoding='utf-8')
    replies = iter([
        ("```mswea_bash_command\npython -c \"import os,pathlib; assert os.getuid()==10001; "
        "assert pathlib.Path('/seed/demo.py').read_text()=='value = 1\\n'; "
        "pathlib.Path('demo.py').write_text('value = 2\\n')\" && "
        "python -c \"import demo; assert demo.value == 2\"\n```"),
        '```mswea_bash_command\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```'])
    events = Events(output / 'trace.jsonl', 'no-inference-docker-smoke')
    # This scripted Model only tests upstream control flow and actual Docker execution.
    provider = SimpleNamespace(model='scripted-not-inference', chat=lambda *a, **k: UsageResponse(
        content=next(replies), reported_usage={'prompt_tokens': 0, 'completion_tokens': 0}))
    llm = BudgetLLM(provider, RunConfig(mode='scripted', max_output_tokens=2048), events)
    policy = adapter.runner.preflight()
    env = adapter.MiniEnvironment(seed, output, policy, events, time.monotonic() + 60)
    try:
        agent = Agent(adapter.MiniModel(llm, settings['model'], output, events), env,
                      **{**settings['agent'], 'step_limit': 3, 'output_path': output / 'trajectory.json'})
        assert agent.run('Change demo.value to 2')['exit_status'] == 'Submitted'
        env.export(output / 'export')
        assert (output / 'export/demo.py').read_text() == 'value = 2\n'
        assert (seed / 'demo.py').read_text() == 'value = 1\n'
        assert (output / 'bash-001.stderr.txt').read_bytes() == b''
    finally:
        env.close()
