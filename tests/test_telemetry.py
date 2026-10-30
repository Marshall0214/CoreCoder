import json
import runpy
from pathlib import Path

import pytest

from repairflow import telemetry

TASK = {'repo': 'test/pkg', 'base_commit': 'a' * 40, 'source_sha256': 'source', 'harness_sha256': 'checks'}
REPORT = {'status': 'public_checks_passed', 'public_checks_passed': True, 'accepted': False,
          'delivery_status': 'ready_for_review', 'changed_files': ['main.py'], 'fresh_model_calls': 0,
          'metrics': {'prompt_tokens': None, 'completion_tokens': None}}


class Span:
    def __init__(self, **kwargs):
        self.values, self.children, self.ended = dict(kwargs), [], False

    def start_observation(self, **kwargs):
        span = Span(**kwargs)
        self.children.append(span)
        return span

    def update(self, **kwargs):
        self.values.update(kwargs)

    def end(self):
        self.ended = True


class Client:
    def __init__(self, **kwargs):
        self.settings, self.root, self.scores, self.closed = kwargs, None, [], False

    def auth_check(self):
        return True

    def start_observation(self, **kwargs):
        self.root = Span(**kwargs)
        return self.root

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        pass

    def get_trace_url(self, trace_id):
        return 'http://127.0.0.1:3300/trace/' + trace_id

    def shutdown(self):
        self.closed = True


@pytest.fixture(autouse=True)
def no_implicit_telemetry(monkeypatch):
    for key in ('CORECODER_LANGFUSE_ENABLED', 'CORECODER_LANGFUSE_ENV_FILE', 'LANGFUSE_PUBLIC_KEY',
                'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL'):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '1')
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'pk-lf-unit-test')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk-lf-unit-test-secret')
    monkeypatch.setenv('LANGFUSE_BASE_URL', 'http://127.0.0.1:3300')


def test_disabled_has_no_sdk_or_network_dependency(tmp_path):
    def forbidden(**kwargs):
        pytest.fail('SDK instantiated while disabled')
    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=forbidden)
    assert observer.finish(REPORT) == {'enabled': False, 'status': 'disabled', 'content_capture': False}


@pytest.mark.parametrize('url', ['https://cloud.langfuse.com', 'http://127.0.0.1.evil.test',
                               'http://user:password@localhost:3300', 'file:///D:/data',
                               'http://localhost:3300/path', 'http://localhost:3300?secret=1'])
def test_local_only_configuration_rejects_remote_and_credential_urls(settings, monkeypatch, url):
    monkeypatch.setenv('LANGFUSE_BASE_URL', url)
    with pytest.raises(ValueError, match='local Langfuse'):
        telemetry.configuration()


def test_env_file_does_not_load_other_credentials_or_change_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'original-host-value')
    path = tmp_path / '.env'
    path.write_text('LANGFUSE_PUBLIC_KEY=pk-lf-file\nLANGFUSE_SECRET_KEY=sk-lf-file\n'
                    'LANGFUSE_BASE_URL=http://localhost:3300\nDEEPSEEK_API_KEY=must-not-load\n', encoding='utf-8')
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '1')
    monkeypatch.setenv('CORECODER_LANGFUSE_ENV_FILE', str(path))
    values = telemetry.configuration()
    assert values['public_key'] == 'pk-lf-file' and set(values) == {'public_key', 'secret_key', 'base_url'}
    assert telemetry.os.environ['DEEPSEEK_API_KEY'] == 'original-host-value'


def test_real_operation_boundaries_and_scores_do_not_claim_independent_acceptance(tmp_path, settings):
    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=Client)
    observer.event('llm_started', {'call_id': 'llm-1', 'request_estimate': 100})
    observer.event('llm_finished', {'call_id': 'llm-1', 'usage_known': False, 'prompt_tokens': None, 'completion_tokens': None})
    observer.event('agent_action_started', {'step': 1, 'action': 'apply_patch',
                                          'arguments': {'edits': [{'file': 'main.py', 'old': 'private-code', 'new': 'secret-code'}]}})
    observer.event('agent_action', {'step': 1, 'action': 'apply_patch', 'status': 'completed',
                                  'result': {'changed_files': ['main.py'], 'content': 'private-code'}})
    observer.event('public_checks_started', {'stage': 'step-001-checks'})
    observer.event('public_checks_finished', {'groups': {'Reproduce': {'passed': True}}, 'passed': True})
    result = observer.finish(REPORT)
    client = observer.client
    assert result['status'] == 'submitted_unconfirmed' and len(result['trace_id']) == 32
    assert client.closed and client.root.ended and all(span.ended for span in client.root.children)
    assert [span.values['as_type'] for span in client.root.children] == ['generation', 'tool', 'span']
    generation = client.root.children[0].values
    assert generation['name'] == 'scripted-response' and generation['usage_details'] is None
    assert 'private-code' not in json.dumps(client.root.children[1].values)
    assert 'secret-code' not in json.dumps(client.root.children[1].values)
    scores = {row['name']: row['value'] for row in client.scores}
    assert scores == {'public_checks_passed': 1, 'independent_verification_available': 0, 'fresh_model_calls': 0}


def test_known_usage_and_failed_read_are_visible_without_raw_errors(tmp_path, settings):
    observer = telemetry.Telemetry(tmp_path, TASK, 'ollama', 'qwen3.5:27b', factory=Client)
    observer.event('llm_started', {'call_id': 'llm-1', 'request_estimate': 10})
    observer.event('llm_finished', {'call_id': 'llm-1', 'usage_known': True, 'prompt_tokens': 20, 'completion_tokens': 5})
    observer.event('agent_action_started', {'step': 1, 'action': 'read_symbol', 'arguments': {'path': 'x.py', 'symbol': 'f'}})
    observer.event('agent_action', {'step': 1, 'action': 'read_symbol', 'status': 'tool_error',
        'error': {'code': 'path_not_allowed', 'retryable': False, 'message': 'raw secret must not be sent'}})
    observer.finish(dict(REPORT, status='nonretryable_tool_error', public_checks_passed=False, fresh_model_calls=1))
    generation, tool = observer.client.root.children
    assert generation.values['usage_details'] == {'input': 20, 'output': 5}
    assert tool.values['level'] == 'ERROR' and tool.values['output']['error_code'] == 'path_not_allowed'
    assert 'raw secret' not in json.dumps(tool.values)


def test_sdk_init_and_update_failures_do_not_change_repair_result(tmp_path, settings):
    def fail(**kwargs):
        raise RuntimeError('sk-lf-secret-value')
    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=fail)
    saved = dict(REPORT)
    state = observer.finish(REPORT)
    assert state['status'] == 'unavailable' and REPORT == saved
    assert 'sk-lf-secret-value' not in json.dumps(state)
    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=Client)
    observer.root.start_observation = fail
    observer.event('llm_started', {'call_id': 'llm-1', 'request_estimate': 10})
    assert observer.finish(REPORT)['status'] == 'partial' and REPORT == saved


def test_observed_events_keep_canonical_local_trace(tmp_path, settings):
    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=Client)
    events = telemetry.ObservedEvents(tmp_path / 'trace.jsonl', 'run', observer)
    events.emit('agent_action_started', step=1, action='read_symbol', arguments={'path': 'main.py', 'symbol': 'f'})
    events.emit('agent_action', step=1, action='read_symbol', status='completed', result={'content': 'full local source'})
    records = [json.loads(line) for line in (tmp_path / 'trace.jsonl').read_text().splitlines()]
    assert records[-1]['result']['content'] == 'full local source'
    assert 'full local source' not in json.dumps(observer.client.root.children[0].values)
    observer.finish(REPORT)


def test_deployment_preparation_generates_secrets_once_and_does_not_overwrite(tmp_path):
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'deploy/langfuse/prepare.py'))
    prepare = module['prepare']
    prepare.__globals__['ROOT'] = tmp_path
    prepare.__globals__['docker_storage'] = lambda: {'docker_disk_directory': 'D:/docker-fixture'}
    destination = tmp_path / '.tmp/local'
    result = prepare(destination)
    text = (destination / '.env').read_text()
    assert result['url'] == 'http://127.0.0.1:3300'
    assert 'LANGFUSE_SECRET_KEY=sk-lf-' in text and 'LANGFUSE_ENCRYPTION_KEY=' in text
    assert 'sk-lf-' not in json.dumps(result)
    with pytest.raises(ValueError, match='fresh'):
        prepare(destination)
    assert (destination / '.env').read_text() == text


def test_installed_sdk_contract_with_in_memory_exporter(tmp_path, settings, monkeypatch):
    sdk = pytest.importorskip('langfuse')
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    monkeypatch.setattr(sdk.Langfuse, 'auth_check', lambda self: True)
    monkeypatch.setattr(sdk.Langfuse, 'create_score', lambda *args, **kwargs: None)
    monkeypatch.setattr(sdk.Langfuse, 'get_trace_url', lambda self, trace_id: 'http://localhost:3300/trace/' + trace_id)

    def factory(**kwargs):
        return sdk.Langfuse(**kwargs, tracer_provider=TracerProvider(), span_exporter=exporter)

    observer = telemetry.Telemetry(tmp_path, TASK, 'scripted', 'scripted-not-a-model', factory=factory)
    observer.event('llm_started', {'call_id': 'llm-1', 'request_estimate': 100})
    observer.event('llm_finished', {'call_id': 'llm-1', 'usage_known': False, 'prompt_tokens': None, 'completion_tokens': None})
    state = observer.finish(REPORT)
    assert state['status'] == 'submitted_unconfirmed'
    spans = exporter.get_finished_spans()
    assert len(spans) == 2 and {span.name for span in spans} == {'issue-repair', 'scripted-response'}
    root = next(span for span in spans if span.name == 'issue-repair')
    child = next(span for span in spans if span.name == 'scripted-response')
    assert child.parent.span_id == root.context.span_id


def test_issue_engine_writes_optional_telemetry_and_keeps_public_acceptance_separate(tmp_path, settings, monkeypatch):
    from repairflow.bundles import read, write
    from repairflow.issue_repair import execute
    from tests.issue_repair_fixture import patch
    from tests.test_issue_repair import task as original_task

    prepared, configuration = original_task.__wrapped__(tmp_path / 'inputs', monkeypatch)
    clients = []

    def factory(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(telemetry, 'client_factory', factory)
    answers = tmp_path / 'responses.json'
    write(answers, [patch()])
    report = execute(prepared, configuration, tmp_path / 'run', mode='scripted', responses=answers,
                     workflow='symbol-recovery-v1')
    assert report['public_checks_passed'] and report['accepted'] is False
    assert report['observability']['status'] == 'submitted_unconfirmed' and report['fresh_model_calls'] == 0
    assert read(tmp_path / 'run/observability.json') == report['observability']
    names = [span.values['name'] for span in clients[0].root.children]
    assert names.count('docker-public-checks') == 2
    assert 'scripted-response' in names and 'apply_patch' in names
