"""Product adapter for initial exploration and public-feedback actions; no private grading."""
import hashlib
import json
import shutil
import time
from pathlib import Path

from evals.context_policy import request_breakdown
from evals.repository_checkpoint import LedgerTools, explore
from evals.runner import changes, digest, snapshot
from evals.runtime import BudgetLLM
from repairflow.bundles import tree_hash
from repairflow.feedback_repair_v2 import run as continue_feedback
from repairflow.github_issue import identity
from repairflow.issue_execution import FEEDBACK, limits, profile
from repairflow.issue_providers import OllamaProvider, ProviderFailure, ScriptedProvider
from repairflow.patch_validator import inside, permitted, save
from repairflow.telemetry import ObservedEvents, Telemetry
from sandbox import runner


class Responses(BudgetLLM):
    """One provider schedule across both phases, with account-only native usage."""
    def __init__(self, inner, events):
        super().__init__(inner, None, events)
        self.phase, self.deadline, self.finished_calls = 'initial', 0, 0

    def chat(self, messages, tools=None, **kwargs):
        if tools or time.monotonic() >= self.deadline:
            raise ProviderFailure('task_timeout' if time.monotonic() >= self.deadline else 'unexpected_native_tools')
        breakdown = request_breakdown(messages, tools, response_format=kwargs.get('response_schema'))
        self.calls += 1
        call_id = f'{self.phase}-{self.calls}'
        started = time.monotonic()
        self.events.emit('llm_started', call_id=call_id, phase=self.phase,
                         request_estimate=breakdown['request_estimate'], message_count=len(messages))
        try:
            self.inner.deadline = self.deadline
            response = self.inner.chat(messages, tools=tools, **dict(kwargs, max_tokens=-1))
            if time.monotonic() >= self.deadline:
                raise ProviderFailure('task_timeout', reported_usage=getattr(response, 'reported_usage', {}))
        except Exception as exc:
            measured = self._account_usage(exc, breakdown['request_estimate'], failed=True)
            self.finished_calls += 1
            self.events.emit('llm_failed', call_id=call_id, phase=self.phase, **measured,
                             seconds=round(time.monotonic() - started, 4), error=type(exc).__name__)
            raise
        measured = self._account_usage(response, breakdown['request_estimate'])
        self.finished_calls += 1
        self.events.emit('llm_finished', call_id=call_id, phase=self.phase, **measured,
                         seconds=round(time.monotonic() - started, 4), tools=[])
        return response

    def metrics(self):
        result = super().metrics()
        pending = self.calls - self.finished_calls
        result.update(token_budget=None, max_output_tokens=None, budget_enforcement='account_only; no token cutoffs',
                      pending_calls=pending, known_tokens_minimum=self.prompt_known + self.completion_known,
                      missing_usage_calls=self.missing_usage + pending)
        if isinstance(self.inner, ScriptedProvider):
            result['budget_accounted_tokens'] = None
        if pending:
            result.update(prompt_tokens=None, completion_tokens=None, usage_status='partial')
        return result


def execute(prepared, configuration, output, *, mode, responses=None, model='qwen3.5:27b',
            execution_profile=None, sandbox_owner_path=None, service_timeout_seconds=None):
    from repairflow.issue_repair import trusted_task

    if mode not in {'scripted', 'ollama'} or (mode == 'scripted') != (responses is not None):
        raise ValueError('Choose recorded responses or an explicit installed Ollama model')
    selected = profile(execution_profile)
    effective = limits(selected, service_timeout_seconds)
    prepared, output = inside(prepared), inside(output)
    task, settings = trusted_task(prepared, configuration)
    inputs = [prepared, Path(configuration).resolve().parent]
    if responses is not None:
        inputs.append(Path(responses).resolve())
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in inputs):
        raise ValueError('Use a fresh output outside all trusted inputs')
    editable = sorted(task['allowed_files'])
    readable = sorted(set(editable + task.get('read_only_files', [])))
    if any(not permitted(name) for name in readable):
        raise ValueError('Feedback policy supports existing non-test Python read/edit paths only')
    owner = inside(sandbox_owner_path) if sandbox_owner_path is not None else output
    if not output.is_relative_to(owner):
        raise ValueError('Sandbox owner must be this output or its trusted task ancestor')
    policy = runner.preflight(settings['image'])
    if policy['image_id'] != task['sandbox']['image_id']:
        raise ValueError('Sandbox image changed since task admission')
    started = time.monotonic()
    deadline = started + effective['total_seconds']
    inner = ScriptedProvider(Path(responses)) if mode == 'scripted' else OllamaProvider(model, deadline)
    output.mkdir(parents=True)
    baseline, initial, public = output / 'baseline', output / 'initial', output / 'public'
    shutil.copytree(prepared / 'source', baseline)
    initial.mkdir()
    shutil.copytree(baseline, initial / 'workspace')
    shutil.copytree(prepared / 'public', public)
    before = snapshot(baseline)
    repo, number = identity(task['issue_url'])
    public_task = {'instance_id': repo.replace('/', '-') + '-issue-' + str(number), 'repo': task['repo'],
                   'base_commit': task['base_commit'], 'problem_statement': task['description']}
    save(output / 'provenance.json', {'engine': FEEDBACK, 'prepared_task_sha256': task['task_sha256'],
        'config_sha256': settings['config_sha256'], 'source_sha256': task['source_sha256'],
        'public_checks_sha256': task['harness_sha256'], 'model': inner.model, 'thinking': False,
        'execution_profile': selected, 'effective_limits': effective, 'sandbox': policy,
        'sandbox_owner_path': str(owner), 'allowed_files': editable, 'read_only_files': task.get('read_only_files', []),
        'scripted_responses_sha256': hashlib.sha256(Path(responses).read_bytes()).hexdigest() if responses else None,
        'implementation_sha256': {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
             for name in ('issue_feedback.py', 'issue_execution.py', 'feedback_repair_v2.py', 'feedback_actions.py',
                          'feedback_context.py', 'issue_providers.py', 'issue_tools.py')}})
    report = {'schema_version': 'prepared-issue-feedback-v2', 'engine': FEEDBACK, 'status': 'running',
              'phase': 'initial', 'accepted': False, 'public_checks_passed': False, 'requires_review': True,
              'delivery_status': 'not_delivered', 'independent_verification': {'available': False, 'passed': None},
              'execution_mode': mode, 'fresh_inference': mode == 'ollama', 'fresh_model_calls': 0,
              'scripted_calls': 0, 'original_unchanged': True, 'execution_profile': selected,
              'effective_limits': effective, 'artifacts': str(output), 'runtime_details': {}, 'changed_files': []}
    save(output / 'report.json', report)
    save(output / 'actions.json', [])
    save(output / 'context-selection.json', {'initial': [], 'feedback': []})
    (output / 'patch.diff').write_text('', encoding='utf-8')
    (output / 'trace.jsonl').write_text('', encoding='utf-8')
    observer = Telemetry(output, task, mode, inner.model)
    save(output / 'observability.json', observer.state)
    actual_events = ObservedEvents(output / 'trace.jsonl', output.name, observer)
    actions = []
    llm = None

    def progress():
        workspace = output / 'feedback/workspace'
        if not workspace.is_dir():
            workspace = initial / 'workspace'
        changed, patch = changes(before, snapshot(workspace))
        (output / 'patch.diff').write_text(patch, encoding='utf-8')
        report.update(changed_files=changed, final_candidate_hash=digest(snapshot(workspace)),
                      original_unchanged=snapshot(prepared / 'source') == before,
                      seconds=round(time.monotonic() - started, 3),
                      fresh_model_calls=llm.calls if llm is not None and mode == 'ollama' else 0,
                      scripted_calls=llm.calls if llm is not None and mode == 'scripted' else 0,
                      metrics=llm.metrics() if llm is not None else {})
        save(output / 'actions.json', actual_events.clean(actions))
        manifests = []
        for path in sorted((output / 'feedback/requests').glob('*/context.json')):
            manifests.append({'request': path.parent.name, **json.loads(path.read_text(encoding='utf-8'))})
        save(output / 'context-selection.json', {'initial': tools.evidence,
                                                'feedback': manifests})
        save(output / 'report.json', actual_events.clean(report))

    class ProgressEvents:
        def clean(self, value):
            return actual_events.clean(value)

        def emit(self, kind, **fields):
            actual_events.emit(kind, **fields)
            if kind == 'agent_action':
                actions.append({'phase': report['phase'], **fields})
            progress()

    events = ProgressEvents()
    llm = Responses(inner, events)
    tools = LedgerTools(initial / 'workspace', initial)
    tools.files, tools.allowed = readable, editable
    try:
        llm.deadline = min(deadline, time.monotonic() + selected['exploration_seconds'])
        state = explore(llm, tools, public_task, initial, events, max_steps=selected['exploration_requests'], max_edits=6)
        report['runtime_details']['initial'] = {'status': state, 'response_calls': llm.calls}
        save(initial / 'report.json', report['runtime_details']['initial'])
        report['phase'] = llm.phase = 'feedback'
        remaining = min(selected['feedback_seconds'], int(deadline - time.monotonic()))
        if remaining < 1:
            raise ProviderFailure('task_timeout')
        llm.deadline = time.monotonic() + remaining
        progress()
        feedback = continue_feedback(baseline, initial / 'workspace', editable, public, task['package'], public_task,
            output / 'feedback', llm=llm, source_root=task['source_root'], readable_files=readable,
            max_feedback_rounds=selected['feedback_requests'], timeout=remaining, context_contract=True,
            context_target_tokens=selected['context_target_tokens'], events=events, sandbox_owner_path=owner,
            sandbox_image_id=policy['image_id'])
        report.update(feedback_counts=feedback['counts'])
        report['runtime_details']['feedback'] = {'status': feedback['status'], 'counts': feedback['counts']}
        ready = feedback['accepted'] is True and feedback['original_inputs_unchanged'] is True
        report.update(status='public_checks_passed' if ready else feedback['status'], public_checks_passed=ready,
                      delivery_status='ready_for_review' if ready else 'not_delivered',
                      final_public_checks=(feedback['last_public_result'] or {}).get('public_checks', {}),
                      pending_candidate_preserved=feedback['pending_candidate_preserved'])
    except ProviderFailure as exc:
        report.update(status=exc.status, failure_type='provider_or_deadline')
    except KeyboardInterrupt:
        report.update(status='cancelled', failure_type='cancelled')
    except Exception as exc:  # noqa: BLE001 - retain all available evidence and no independent acceptance
        report.update(status='agent_error', failure_type=type(exc).__name__)
    finally:
        progress()
        if not report['original_unchanged'] or not report['changed_files']:
            report.update(public_checks_passed=False, delivery_status='not_delivered')
            if report['status'] == 'public_checks_passed':
                report['status'] = 'no_net_source_change'
        try:
            retained, _ = trusted_task(prepared, configuration)
            if retained['task_sha256'] != task['task_sha256'] or tree_hash(public) != task['harness_sha256']:
                raise ValueError('Prepared inputs changed')
        except (OSError, ValueError, TypeError, KeyError):
            report.update(status='input_integrity_failed', original_unchanged=False,
                          public_checks_passed=False, delivery_status='not_delivered')
        report['phase'] = 'finished'
        report['provider_calls'] = inner.calls
        report['observability'] = observer.finish(report)
        save(output / 'observability.json', report['observability'])
        save(output / 'report.json', actual_events.clean(report))
    return report
