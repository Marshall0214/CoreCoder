"""Optional local Langfuse telemetry; never controls repair or acceptance decisions."""
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

from evals.runtime import Events


def configuration():
    if os.environ.get('CORECODER_LANGFUSE_ENABLED') != '1':
        return None
    values = {}
    path = os.environ.get('CORECODER_LANGFUSE_ENV_FILE')
    if path:
        from dotenv import dotenv_values

        values = dotenv_values(Path(path))
    # Only these settings are read. Database/login/model credentials are never loaded.
    values = {key: os.environ.get(key) or values.get(key) for key in
              ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL')}
    url = urlsplit(values['LANGFUSE_BASE_URL'] or '')
    if (url.scheme not in {'http', 'https'} or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}
            or not all(isinstance(value, str) and value for value in values.values())):
        raise ValueError('Require local Langfuse URL and project credentials')
    return {'public_key': values['LANGFUSE_PUBLIC_KEY'], 'secret_key': values['LANGFUSE_SECRET_KEY'],
            'base_url': values['LANGFUSE_BASE_URL'].rstrip('/')}


def client_factory(**kwargs):
    # The repair engine works without this optional SDK installed.
    from langfuse import Langfuse

    return Langfuse(**kwargs)


def action_summary(fields):
    """Only typed summaries; prompts, code, anchors and test logs stay in local artifacts."""
    summary = {key: fields[key] for key in ('step', 'action', 'status', 'reason') if key in fields}
    args = fields.get('arguments') or {}
    summary.update({key: args[key] for key in ('path', 'symbol', 'offset') if key in args})
    if isinstance(args.get('edits'), list):
        summary['edited_files'] = [row.get('file') for row in args['edits'] if isinstance(row, dict)]
    result = fields.get('result') or {}
    summary.update({key: result[key] for key in ('path', 'symbol', 'kind', 'content_hash', 'next_offset', 'changed_files')
                    if key in result})
    if isinstance(fields.get('error'), dict):
        summary['error_code'] = fields['error'].get('code')
        summary['retryable'] = fields['error'].get('retryable')
    if fields.get('public_check_feedback'):
        summary['public_feedback_code'] = fields['public_check_feedback'].get('code')
    return summary


class Telemetry:
    def __init__(self, output, task, mode, model, factory=None):
        self.client = self.root = None
        self.spans = {}
        self.state = {'enabled': False, 'status': 'disabled', 'content_capture': False}
        try:
            settings = configuration()
            if settings is None:
                return
            self.state.update(enabled=True, status='initializing')
            self.client = (factory or client_factory)(**settings, timeout=2, flush_at=1, flush_interval=0.5,
                                                    environment='local-development')
            if not self.client.auth_check():
                raise ValueError('Langfuse authentication unavailable')
            trace_id = hashlib.sha256(str(Path(output).resolve()).encode()).hexdigest()[:32]
            self.root = self.client.start_observation(name='issue-repair', as_type='agent',
                trace_context={'trace_id': trace_id}, metadata={
                    'execution_mode': mode, 'fresh_inference': mode == 'ollama', 'model': model,
                    'repo': task['repo'], 'base_commit': task['base_commit'],
                    'source_sha256': task['source_sha256'], 'harness_sha256': task['harness_sha256'],
                    'independent_verification_available': False})
            self.state.update(status='recording', trace_id=trace_id, base_url=settings['base_url'])
            self.mode, self.model = mode, model
        except Exception as exc:  # noqa: BLE001 - observability is optional, never break task execution
            self._error(exc)

    def _error(self, exc):
        self.state['status'] = 'unavailable' if self.root is None else 'partial'
        self.state.setdefault('error_types', []).append(type(exc).__name__)
        self.state['error_types'] = self.state['error_types'][-8:]

    def _start(self, key, name, kind, **kwargs):
        self.spans[key] = self.root.start_observation(name=name, as_type=kind, **kwargs)

    def _end(self, key, **kwargs):
        span = self.spans.pop(key, None)
        if span is not None:
            if kwargs:
                span.update(**kwargs)
            span.end()

    def event(self, kind, fields):
        if self.root is None:
            return
        try:
            if kind == 'llm_started':
                self._start(fields['call_id'], 'model-call' if self.mode == 'ollama' else 'scripted-response',
                            'generation', model=self.model, metadata={
                                'execution_mode': self.mode, 'request_estimate': fields['request_estimate'],
                                'fresh_inference': self.mode == 'ollama'})
            elif kind == 'llm_finished':
                usage = {'input': fields['prompt_tokens'], 'output': fields['completion_tokens']} if fields['usage_known'] else None
                self._end(fields['call_id'], usage_details=usage, metadata={'usage_known': fields['usage_known']})
            elif kind == 'llm_failed':
                self._end(fields['call_id'], level='ERROR', status_message='Provider failure; see local trace')
            elif kind == 'agent_action_started':
                self._start('action-' + str(fields['step']), fields['action'], 'tool', input=action_summary(fields))
            elif kind == 'agent_action':
                failed = fields.get('status') in {'tool_error', 'stopped'}
                self._end('action-' + str(fields['step']), output=action_summary(fields), level='ERROR' if failed else 'DEFAULT')
            elif kind == 'public_checks_started':
                self._start('checks', 'docker-public-checks', 'span', metadata={'stage': fields['stage']})
            elif kind == 'public_checks_finished':
                self._end('checks', output=fields['groups'], level='DEFAULT' if fields['passed'] else 'WARNING')
            elif kind == 'public_checks_failed':
                self._end('checks', level='ERROR', status_message='Check execution failed; see local trace')
            elif kind == 'budget_blocked':
                span = self.root.start_observation(name='budget-stop', as_type='guardrail',
                    metadata={key: fields[key] for key in ('reason', 'remaining', 'token_budget') if key in fields}, level='WARNING')
                span.end()
        except Exception as exc:  # noqa: BLE001 - SDK errors cannot affect tool or budget behavior
            self._error(exc)

    def finish(self, report):
        try:
            if self.root is not None:
                for key in list(self.spans):
                    self._end(key, level='WARNING', status_message='Task ended before operation completed')
                self.root.update(output={key: report.get(key) for key in ('status', 'public_checks_passed',
                    'delivery_status', 'accepted', 'changed_files')}, metadata={'metrics': report.get('metrics'),
                    'fresh_model_calls': report.get('fresh_model_calls'), 'independent_verification_available': False})
                self.root.end()
                for name, value in [('public_checks_passed', int(report.get('public_checks_passed') is True)),
                                    ('independent_verification_available', 0)]:
                    self.client.create_score(trace_id=self.state['trace_id'], name=name, value=value, data_type='BOOLEAN')
                self.client.create_score(trace_id=self.state['trace_id'], name='fresh_model_calls',
                                         value=report.get('fresh_model_calls', 0), data_type='NUMERIC')
                self.client.flush()
                # Flush means submitted, not independently confirmed stored by the server.
                if self.state['status'] == 'recording':
                    self.state['status'] = 'submitted_unconfirmed'
                self.state['trace_url'] = self.client.get_trace_url(trace_id=self.state['trace_id'])
        except Exception as exc:  # noqa: BLE001 - a telemetry outage cannot discard a valid repair report
            self._error(exc)
        finally:
            if self.client is not None:
                try:
                    self.client.shutdown()
                except Exception as exc:  # noqa: BLE001 - preserve original task result
                    self._error(exc)
        return dict(self.state)


class ObservedEvents(Events):
    def __init__(self, path, run_id, observer):
        super().__init__(path, run_id)
        self.observer = observer

    def emit(self, kind, **fields):
        super().emit(kind, **fields)
        self.observer.event(kind, self.clean(fields))
