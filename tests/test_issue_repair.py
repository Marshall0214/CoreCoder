import json
import sys

import pytest

from repairflow import __main__ as cli
from repairflow import issue_providers as providers
from repairflow import issue_repair as module
from repairflow.bundles import read, write
from sandbox import runner
from tests.issue_repair_fixture import SOURCE, patch, prepare_fixture
from tests.test_github_issue import outcome

POLICY = {'backend': 'docker', 'image_id': 'sha256:' + '1' * 64}


@pytest.fixture
def task(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'preflight', lambda image=None: dict(POLICY))

    def run(source, harness, package, source_root, logs, name, *args):
        code = (source / 'src/pkg/__init__.py').read_text(encoding='utf-8')
        failed = name == 'Reproduce' and 'return x + 2' not in code
        logs.mkdir(exist_ok=True)
        (logs / (name + '.stderr.txt')).write_text('AssertionError: target not fixed' if failed else '', encoding='utf-8')
        return outcome(failed, timed_out=False)

    monkeypatch.setattr(runner, 'run', run)
    return prepare_fixture(tmp_path)


def run_scripted(tmp_path, task, rows, **kwargs):
    response = tmp_path / 'responses.json'
    write(response, rows)
    return module.execute(*task, tmp_path / 'run', mode='scripted', responses=response, **kwargs)


def test_public_pass_is_reviewable_but_never_independent_acceptance(tmp_path, task, monkeypatch):
    # Legacy local backends must not bypass this flow's mandatory container runner.
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')
    monkeypatch.setattr(providers.OllamaProvider, 'chat', lambda *a, **kw: pytest.fail('Unexpected model request'))
    report = run_scripted(tmp_path, task, [patch()])
    assert report['status'] == 'public_checks_passed' and report['public_checks_passed']
    assert report['delivery_status'] == 'ready_for_review' and report['requires_review']
    assert report['accepted'] is False and report['independent_verification'] == {'available': False, 'passed': None}
    assert report['fresh_model_calls'] == 0 and report['scripted_calls'] == 1 and not report['fresh_inference']
    assert report['metrics']['prompt_tokens'] is None
    assert report['original_unchanged'] and (task[0] / 'source/src/pkg/__init__.py').read_text() == SOURCE
    assert '+    return x + 2' in (tmp_path / 'run/patch.diff').read_text()
    assert not (tmp_path / 'run/grader').exists()


def test_one_feedback_correction_uses_current_code_and_public_evidence(tmp_path, task):
    report = run_scripted(tmp_path, task, [patch(new=4), patch(old=4)])
    assert report['public_checks_passed'] and len(report['attempts']) == 2
    payload = json.loads(read(tmp_path / 'run/correction-messages.json')[1]['content'])
    assert 'return x + 4' in json.dumps(payload['fragments'])
    assert 'AssertionError' in payload['public_check_feedback']['observations']
    assert 'public_test_code' in payload and 'grader' not in payload and 'frozen' not in payload


def test_correction_back_to_original_is_explicit_no_progress(tmp_path, task):
    report = run_scripted(tmp_path, task, [patch(new=4), patch(old=4, new=1)])
    assert report['status'] == 'no_progress' and report['no_progress_detected']
    assert report['attempts'][1]['diagnostic'] == 'no_net_source_change'
    assert report['attempts'][1]['net_changed_files'] == []
    assert not report['public_checks_passed'] and (tmp_path / 'run/patch.diff').read_text() == ''
    assert (tmp_path / 'run/correction-checks/Reproduce.stderr.txt').exists()


def test_successful_correction_is_not_called_no_progress(tmp_path, task):
    report = run_scripted(tmp_path, task, [patch(new=4), patch(old=4)])
    assert report['public_checks_passed'] and not report['no_progress_detected']
    assert report['attempts'][1]['net_changed_files'] == ['src/pkg/__init__.py']


@pytest.mark.parametrize('policy', ['baseline', 'module-bindings-v1'])
def test_context_policy_is_explicit_and_recorded(tmp_path, task, policy):
    report = run_scripted(tmp_path, task, [patch()], context_policy=policy)
    assert report['public_checks_passed'] and report['context_policy'] == policy
    assert read(tmp_path / 'run/provenance.json')['context_policy'] == policy
    actual = read(tmp_path / 'run/initial-context.json')['metadata']['policy']
    assert actual == ('coverage-context-v2' if policy == 'baseline' else policy)


def test_unknown_context_policy_rejected_before_loading_inputs(tmp_path):
    with pytest.raises(ValueError, match='context policy'):
        module.execute(tmp_path / 'missing', tmp_path / 'missing.json', tmp_path / 'run',
                       mode='ollama', context_policy='unknown')


@pytest.mark.parametrize('responses', [[patch(new=4), '{}'], ['{"edits":[]}', '{}'],
                                      [patch(new='('), '{}'], [patch(new=1), '{}']])
def test_failed_or_invalid_patch_is_rolled_back_with_no_delivery(tmp_path, task, responses):
    report = run_scripted(tmp_path, task, responses)
    assert not report['public_checks_passed'] and report['delivery_status'] == 'not_delivered'
    assert report['candidate_rolled_back'] and len(report['attempts']) == 2
    assert (tmp_path / 'run/workspace/src/pkg/__init__.py').read_text() == SOURCE
    assert (tmp_path / 'run/patch.diff').read_text() == ''
    assert (tmp_path / 'run/report.json').is_file()


def test_forbidden_patch_cannot_escape_workspace(tmp_path, task):
    bad = json.dumps({'edits': [{'file': '../outside.py', 'old': 'return x + 1', 'new': 'return x + 2'}]})
    report = run_scripted(tmp_path, task, [bad, bad])
    assert not report['public_checks_passed'] and not (tmp_path / 'outside.py').exists()


@pytest.mark.parametrize('mutate', ['config', 'scope', 'description', 'checks'])
def test_untrusted_or_stale_inputs_rejected_before_provider(tmp_path, task, mutate):
    prepared, config = task
    if mutate == 'config':
        config.write_text(config.read_text() + '\n')
    elif mutate == 'checks':
        (prepared / 'public/test_admission.py').write_text('changed')
    else:
        data = read(prepared / 'task.json')
        data['allowed_files' if mutate == 'scope' else 'description'] = ['../outside.py'] if mutate == 'scope' else 'changed'
        write(prepared / 'task.json', data)
    with pytest.raises(ValueError):
        run_scripted(tmp_path, task, [patch()])
    assert not (tmp_path / 'run').exists()


def test_image_change_rejected_before_provider(tmp_path, task, monkeypatch):
    monkeypatch.setattr(runner, 'preflight', lambda image: {**POLICY, 'image_id': 'changed'})
    with pytest.raises(ValueError, match='image changed'):
        run_scripted(tmp_path, task, [patch()])
    assert not (tmp_path / 'run').exists()


def test_unavailable_docker_has_no_host_fallback(tmp_path, task, monkeypatch):
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')
    monkeypatch.setattr(runner, 'preflight', lambda image: (_ for _ in ()).throw(runner.SandboxError('sandbox_unavailable')))
    with pytest.raises(runner.SandboxError):
        run_scripted(tmp_path, task, [patch()])
    assert not (tmp_path / 'run').exists()


def test_baseline_must_still_reproduce_before_inference(tmp_path, task, monkeypatch):
    monkeypatch.setattr(runner, 'run', lambda *a: outcome(timed_out=False))
    report = run_scripted(tmp_path, task, [patch()])
    assert report['status'] == 'baseline_admission_failed' and report['scripted_calls'] == 0


def test_sandbox_fault_stops_without_using_correction(tmp_path, task, monkeypatch):
    real = runner.run

    def run(*args):
        if args[4].name != 'baseline':
            raise runner.SandboxError('sandbox_timeout')
        return real(*args)

    monkeypatch.setattr(runner, 'run', run)
    report = run_scripted(tmp_path, task, [patch()])
    assert report['status'] == 'sandbox_timeout' and not report['public_checks_passed']
    assert len(report['attempts']) == 1 and (tmp_path / 'run/initial-patch.diff').exists()
    assert (tmp_path / 'run/patch.diff').read_text() == ''


def test_provider_truncation_does_not_apply_partial_output_or_retry(tmp_path, task, monkeypatch):
    def chat(self, *args, **kwargs):
        self.calls.append({'scripted': True})
        raise providers.ProviderFailure('incomplete_model_response')

    monkeypatch.setattr(providers.ScriptedProvider, 'chat', chat)
    report = run_scripted(tmp_path, task, [patch(), patch()])
    assert report['status'] == 'incomplete_model_response' and report['scripted_calls'] == 1
    assert not report['public_checks_passed'] and (tmp_path / 'run/patch.diff').read_text() == ''


def test_budget_excess_stops_before_patch_execution(tmp_path, task, monkeypatch):
    from corecoder.llm import LLMResponse

    def chat(self, *args, **kwargs):
        self.calls.append({'scripted': True})
        return LLMResponse(content=patch(), prompt_tokens=60000, completion_tokens=1)

    monkeypatch.setattr(providers.ScriptedProvider, 'chat', chat)
    report = run_scripted(tmp_path, task, [patch()])
    assert report['status'] == 'budget_exceeded' and report['scripted_calls'] == 1
    assert not report['public_checks_passed'] and (tmp_path / 'run/patch.diff').read_text() == ''


def test_changed_preparation_during_generation_is_not_delivered(tmp_path, task, monkeypatch):
    real = providers.ScriptedProvider.chat

    def chat(self, *args, **kwargs):
        (task[0] / 'issue.json').write_text('{}')
        return real(self, *args, **kwargs)

    monkeypatch.setattr(providers.ScriptedProvider, 'chat', chat)
    report = run_scripted(tmp_path, task, [patch()])
    assert report['status'] == 'agent_error' and not report['public_checks_passed']
    assert (tmp_path / 'run/patch.diff').read_text() == ''


@pytest.mark.parametrize('mode,responses', [('live', None), ('ollama', 'path'), ('scripted', None)])
def test_explicit_supported_provider_selection_required(tmp_path, mode, responses):
    with pytest.raises(ValueError, match='Choose'):
        module.execute(tmp_path / 'missing', tmp_path / 'missing.json', tmp_path / 'run', mode=mode, responses=responses)


def test_cli_reports_public_only_success(tmp_path, task, monkeypatch, capsys):
    response = tmp_path / 'responses.json'
    write(response, [patch()])
    monkeypatch.setattr(sys, 'argv', ['repairflow', 'repair-issue', '--prepared', str(task[0]), '--config', str(task[1]),
                                    '--output', str(tmp_path / 'run'), '--mode', 'scripted', '--responses', str(response)])
    assert cli.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data['public_checks_passed'] and not data['accepted'] and data['fresh_model_calls'] == 0


@pytest.mark.parametrize('mode', ['success', 'length', 'thinking', 'tool', 'bad_usage', 'redirect'])
def test_local_native_request_disables_thinking_and_rejects_incomplete_results(monkeypatch, mode):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sentinel-never-sent')
    monkeypatch.setenv('HTTP_PROXY', 'http://untrusted.invalid')
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            message = {'content': patch()}
            if mode == 'thinking':
                message['thinking'] = 'not allowed'
            if mode == 'tool':
                message['tool_calls'] = [{'function': {}}]
            return json.dumps({'done': True, 'done_reason': 'length' if mode == 'length' else 'stop',
                               'model': 'qwen3.5:27b', 'message': message,
                               'prompt_eval_count': 'invalid' if mode == 'bad_usage' else 12, 'eval_count': 5}).encode()

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if mode == 'redirect':
                raise ValueError('Redirect rejected')
            return Response()

    def build(*handlers):
        assert handlers[0].proxies == {}
        return Opener()

    monkeypatch.setattr(providers.urllib.request, 'build_opener', build)
    inner = providers.OllamaProvider('qwen3.5:27b', providers.time.monotonic() + 30)
    if mode == 'success':
        assert inner.chat([]).prompt_tokens == 12
    else:
        with pytest.raises(providers.ProviderFailure):
            inner.chat([])
    payload = json.loads(requests[0].data)
    assert payload['think'] is False and payload['stream'] is False
    assert requests[0].full_url == 'http://127.0.0.1:11434/api/chat'
    assert 'sentinel' not in requests[0].data.decode() and not requests[0].has_header('Authorization')


@pytest.mark.parametrize('model', ['qwen-cloud', 'https://evil/model', 'model@cloud', 'bad model'])
def test_cloud_model_names_rejected_without_requests(model):
    with pytest.raises(ValueError, match='local Ollama'):
        providers.OllamaProvider(model, 0)
