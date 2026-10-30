"""Diagnostics must not confuse an accessible UI or old trace with healthy ingestion."""
import json

import httpx
import pytest

from deploy.langfuse.doctor import check, compose
from deploy.langfuse.drill import fault

SETTINGS = {'base_url': 'http://127.0.0.1:3300', 'public_key': 'pk-test', 'secret_key': 'secret-test'}


def doctor(*, paused=False, database=200, auth=200, observations=1, worker_error=False):
    calls = []

    def run(args):
        calls.append(args)
        if '--quiet' in args:
            return ('b' if args[-1] == 'worker' else 'a') * 64
        if 'inspect' in args:
            return json.dumps({'Status': 'running', 'Running': True,
                               'Paused': paused and args[-1] == 'b' * 64,
                               'Health': {'Status': 'healthy'}, 'Error': 'private-not-for-output'})
        if worker_error:
            raise TimeoutError('private-not-for-output')
        return '200'

    def respond(request):
        if request.url.path.endswith('/projects'):
            return httpx.Response(auth, json={'data': [{'id': 'corecoder-issues'}]})
        if request.url.path.endswith('/observations'):
            return httpx.Response(200, json={'data': [{}] * observations})
        return httpx.Response(database if request.url.query else 200, json={})

    result = check(SETTINGS, 'local.env', 'a' * 32, run=run, transport=httpx.MockTransport(respond))
    assert 'secret-test' not in json.dumps(result) and 'private-not-for-output' not in json.dumps(result)
    return result, calls


def test_healthy_checks_do_not_claim_fresh_ingestion():
    result, _ = doctor()
    assert result['status'] == 'healthy'
    assert result['historical_readback']['found']
    assert result['historical_readback']['proves_fresh_ingestion'] is False
    assert result['fresh_model_calls'] == 0


def test_paused_worker_is_degraded_despite_live_web_and_old_trace():
    result, calls = doctor(paused=True)
    assert result['status'] == 'degraded'
    assert result['checks']['web_liveness']['passed']
    assert result['historical_readback']['found']
    assert not result['checks']['worker_health']['passed']
    assert not any('exec' in args for args in calls)


def test_database_failure_is_not_hidden_by_liveness():
    result, _ = doctor(database=503)
    assert result['status'] == 'degraded'
    assert result['checks']['web_liveness']['passed']
    assert not result['checks']['web_database']['passed']


def test_failed_auth_and_missing_trace_are_distinct():
    result, _ = doctor(auth=401, observations=0)
    assert result['status'] == 'degraded'
    assert result['checks']['project_auth']['http_status'] == 401
    assert result['historical_readback']['found'] is False


def test_worker_endpoint_failure_is_reported_without_raw_error():
    result, _ = doctor(worker_error=True)
    assert result['status'] == 'degraded'
    assert result['checks']['worker_health']['error_type'] == 'TimeoutError'


@pytest.mark.parametrize('service,operation,restore', [('web', 'stop', 'up'), ('worker', 'pause', 'unpause')])
def test_fault_scope_restores_after_task_failure(monkeypatch, service, operation, restore):
    calls = []
    monkeypatch.setattr('deploy.langfuse.drill.docker', lambda env, *args: calls.append(args))
    with pytest.raises(RuntimeError), fault('local.env', service):
        raise RuntimeError('Task failed')
    assert calls[0] == (operation, service)
    assert calls[1][0] == restore and calls[1][-1] == service


def test_fault_scope_restores_after_partial_pause_failure(monkeypatch):
    calls = []

    def docker(env, *args):
        calls.append(args)
        if args[0] == 'pause':
            raise RuntimeError('Docker response lost')

    monkeypatch.setattr('deploy.langfuse.drill.docker', docker)
    with pytest.raises(RuntimeError), fault('local.env', 'worker'):
        pytest.fail('Partial pause must abort')
    assert calls == [('pause', 'worker'), ('unpause', 'worker')]


def test_compose_project_is_pinned_independently_of_host_environment(monkeypatch):
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'unrelated-project')
    args = compose('local.env', 'stop', 'web')
    assert args[args.index('--project-name') + 1] == 'corecoder-langfuse'


def test_docker_and_http_unavailable_produce_redacted_degraded_report():
    def run(args):
        raise FileNotFoundError('private-docker-location')

    def respond(request):
        raise httpx.ConnectError('private-connection-information', request=request)

    result = check(SETTINGS, 'local.env', run=run, transport=httpx.MockTransport(respond))
    assert result['status'] == 'degraded'
    assert result['checks']['container:web']['error_type'] == 'FileNotFoundError'
    assert result['checks']['web_liveness']['error_type'] == 'ConnectError'
    assert 'private-' not in json.dumps(result)
