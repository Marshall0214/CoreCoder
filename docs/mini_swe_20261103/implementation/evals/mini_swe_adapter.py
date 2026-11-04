"""Loopback Ollama and restricted Docker adapters for the unmodified mini-SWE Agent."""
import json
import os
import time
import urllib.request
import uuid

from evals.swebench_agent import extract_text
from repairflow.github_issue import NoRedirect
from repairflow.issue_providers import OllamaProvider, ProviderFailure, UsageResponse
from sandbox import runner


def configure(home):
    # Set before importing upstream: its module creates its global configuration directory.
    os.environ.update(MSWEA_GLOBAL_CONFIG_DIR=str(home), MSWEA_SILENT_STARTUP='1',
                      MSWEA_GLOBAL_COST_LIMIT='0', MSWEA_GLOBAL_CALL_LIMIT='0', PYTHON_DOTENV_DISABLED='1')


class TextOllamaProvider(OllamaProvider):
    """Same local model/settings/usage evidence, with upstream text actions instead of JSON format."""
    def chat(self, messages, tools=None, max_tokens=2048):
        if tools:
            raise ValueError('This adapter uses upstream text-based Bash actions')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFailure('task_timeout')
        payload = {'model': self.model, 'messages': messages, 'stream': False, 'think': False,
                   'options': {'temperature': 0, 'num_predict': max_tokens, 'num_ctx': 65536}}
        record = {'thinking_requested': False, 'transport': 'native_ollama_text', 'usage_known': False}
        self.calls.append(record)
        usage = {}
        try:
            request = urllib.request.Request('http://127.0.0.1:11434/api/chat', json.dumps(payload).encode(),
                                             {'Content-Type': 'application/json'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=min(480, remaining)) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ProviderFailure('provider_response_limit')
            data = json.loads(raw)
            usage = {key: data.get(native) if type(data.get(native)) is int and data[native] >= 0 else None
                     for key, native in [('prompt_tokens', 'prompt_eval_count'), ('completion_tokens', 'eval_count')]}
            record.update(usage, usage_known=all(value is not None for value in usage.values()),
                          finish_reason=data.get('done_reason'), model_returned=data.get('model'))
            if data.get('done') is not True or data.get('done_reason') != 'stop':
                raise ProviderFailure('incomplete_model_response')
            message = data['message']
            if message.get('thinking') or message.get('tool_calls') or not isinstance(message.get('content'), str):
                raise ProviderFailure('unexpected_model_response')
            return UsageResponse(content=message['content'], reported_usage=usage)
        except ProviderFailure as exc:
            record['failure'] = exc.status
            exc.reported_usage = dict(usage)
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            record['failure'] = 'local_provider_failed'
            raise ProviderFailure('local_provider_failed', reported_usage=usage) from exc


class MiniModel:
    """Use upstream parsing/observation formatting and its original linear history."""
    def __init__(self, llm, settings, output, events):
        self.llm, self.settings, self.output, self.events = llm, settings, output, events

    def query(self, messages, **kwargs):
        from minisweagent.exceptions import FormatError
        from minisweagent.models.utils.actions_text import parse_regex_actions

        clean = [{key: row[key] for key in ('role', 'content')} for row in messages]
        write_path = self.output / f'call-{self.llm.calls + 1:03d}-messages.json'
        write_path.write_text(json.dumps(self.events.clean(clean), ensure_ascii=False, indent=2), encoding='utf-8')
        response = self.llm.chat(clean, tools=[])
        (self.output / f'call-{self.llm.calls:03d}-response.txt').write_text(
            self.events.clean(response.content), encoding='utf-8')
        try:
            actions = parse_regex_actions(response.content, action_regex=r'```mswea_bash_command\s*\n(.*?)\n```',
                                          format_error_template=self.settings['format_error_template'])
        except FormatError as exc:
            exc.messages[0]['extra']['cost'] = 0.0
            raise
        return {'role': 'assistant', 'content': response.content, 'extra': {'actions': actions, 'cost': 0.0}}

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars=None):
        from minisweagent.models.utils.actions_text import format_observation_messages

        return format_observation_messages(outputs, observation_template=self.settings['observation_template'],
                                           template_vars=template_vars)

    def get_template_vars(self, **kwargs):
        return {'model_name': self.llm.model}

    def serialize(self):
        return {'info': {'model_adapter': 'local Ollama text + upstream parser', 'thinking': False,
                         'model_metrics': self.llm.metrics()}}


class MiniEnvironment:
    """Non-root task workspace with no writable host mounts."""
    def __init__(self, seed, output, policy, events, deadline):
        self.name = 'corecoder-mini-' + uuid.uuid4().hex
        self.output, self.policy, self.events, self.deadline = output, policy, events, deadline
        self.steps = 0
        self.created = False
        try:
            args = ['create', '--name', self.name, '--label', 'corecoder.mini.owner=' + runner.owner(output),
                    '--network', 'none', '--user', '10001:10001', '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--cpus', '1', '--memory', '1g', '--memory-swap', '1g',
                    '--pids-limit', '64', '--init', '--log-driver', 'none', '--pull', 'never',
                    '--tmpfs', '/workspace:rw,nosuid,nodev,size=128m,uid=10001,gid=10001,mode=0700',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,mode=1777', '--workdir', '/workspace',
                    '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONIOENCODING=utf-8',
                    '--env', 'HOME=/tmp', '--env', 'PYTHONPATH=/workspace/src:/workspace',
                    '--mount', f'type=bind,source={seed.resolve()},target=/seed,readonly',
                    '--entrypoint', '/bin/sh', policy['image_id'], '-c',
                    'cp -R /seed/. /workspace && chmod -R u+rwX /workspace && touch /tmp/ready && sleep 1200']
            if ',' in str(seed):
                raise ValueError('Comma in seed mount path')
            runner.control(args)
            self.created = True
            runner.control(['start', self.name])
            for _ in range(50):
                try:
                    runner.control(['exec', self.name, 'test', '-f', '/tmp/ready'], timeout=3)
                    break
                except runner.SandboxError:
                    time.sleep(0.1)
            else:
                raise runner.SandboxError('mini_workspace_setup_failed')
        except Exception:
            self.close()
            raise

    def execute(self, action, cwd='', *, timeout=None):
        from minisweagent.exceptions import InterruptAgentFlow, Submitted

        if not isinstance(action, dict) or set(action) != {'command'} or not isinstance(action['command'], str):
            raise ValueError('Upstream Bash action requires a command')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise InterruptAgentFlow({'role': 'exit', 'content': 'task_timeout',
                                      'extra': {'exit_status': 'task_timeout', 'submission': ''}})
        self.steps += 1
        record = {'step': self.steps, 'action': 'bash', 'arguments': action}
        self.events.emit('agent_action_started', **record)
        code, out, err, timed_out, overflow = runner.bounded(
            ['exec', '-w', '/workspace', self.name, 'bash', '-lc', action['command']], min(30, remaining), 1048576)
        (self.output / f'bash-{self.steps:03d}.stdout.txt').write_bytes(out)
        (self.output / f'bash-{self.steps:03d}.stderr.txt').write_bytes(err)
        status = 'command_timeout' if timed_out else 'command_output_limit' if overflow else 'completed'
        self.events.emit('agent_action', **record, status=status, result={'returncode': code})
        if timed_out or overflow:
            raise InterruptAgentFlow({'role': 'exit', 'content': status, 'extra': {'exit_status': status, 'submission': ''}})
        result = {'output': (out + err).decode('utf-8', errors='replace'), 'returncode': code, 'exception_info': ''}
        # Exact standard submission marker, never treat ordinary prose as completion.
        lines = result['output'].lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT' and code == 0:
            raise Submitted({'role': 'exit', 'content': ''.join(lines[1:]),
                             'extra': {'exit_status': 'Submitted', 'submission': ''.join(lines[1:])}})
        return result

    def export(self, destination):
        code, raw, _err, timed_out, overflow = runner.bounded(
            ['exec', self.name, 'tar', '-C', '/workspace', '-cf', '-', '.'], 30, 80_000_000)
        if code or timed_out or overflow:
            raise runner.SandboxError('mini_workspace_export_failed')
        # Docker tar emits ./ prefixes; normalize names without extracting paths.
        import io
        import tarfile

        buffer = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(raw)) as source, tarfile.open(fileobj=buffer, mode='w') as target:
            for member in source:
                if member.name in {'.', './'}:
                    continue
                member.name = member.name.removeprefix('./')
                stream = source.extractfile(member) if member.isfile() else None
                target.addfile(member, stream)
        return extract_text(buffer.getvalue(), destination)

    def get_template_vars(self, **kwargs):
        return {'system': 'Linux', 'release': 'isolated Docker', 'version': '', 'machine': 'x86_64', 'cwd': '/workspace'}

    def serialize(self):
        return {'info': {'environment_adapter': 'non-root offline tmpfs workspace', 'sandbox': self.policy,
                         'command_count': self.steps, 'host_writable_mounts': False}}

    def close(self):
        if self.created:
            runner.control(['rm', '-f', self.name])
            self.created = False
