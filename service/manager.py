"""Bounded local queue, durable lifecycle state, and per-task process trees."""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from evals.process import terminate_tree
from service.store import TaskStore

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {'succeeded', 'ready_for_review', 'failed', 'rejected', 'cancelled', 'timed_out', 'interrupted'}
APPROVAL_WORKFLOWS = {'langgraph-approval-v1', 'tentative-approval-v1', 'repair-approval-v1', 'issue-approval-v1'}
ISSUE_ARTIFACTS = frozenset({'patch.diff', 'report.json', 'agent-initial-context.json', 'context-selection.json',
                             'trace.jsonl', 'provenance.json', 'actions.json', 'observability.json'})
PARTIAL_ISSUE_STATES = frozenset({'cancelled', 'timed_out', 'interrupted'})


def issue_artifact_path(job, name):
    """Issue executors publish fixed top-level files; never follow linked ancestors."""
    if job.request.get('workflow') != 'issue-approval-v1' or name not in ISSUE_ARTIFACTS:
        raise ValueError('Unknown Issue artifact')
    root = job.root.absolute() / 'runs'
    path = root / name
    for part in (path, *path.parents):
        try:
            stat = part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 1024:
            raise ValueError('Linked Issue artifacts are unavailable')
    if not path.is_file():
        return None
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Issue artifact escaped its output directory')
    return path


def partial_issue_report(job, state):
    """Lifecycle status is separate from any earlier public-check result."""
    path = issue_artifact_path(job, 'report.json')
    if path is None:
        return None
    report = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        raise TypeError('Invalid Issue report')
    return dict(report, engine_status=report.get('engine_status', report.get('status')), status=state,
                lifecycle_state=state, accepted=False, public_checks_passed=False, partial_result=True,
                delivery_status='not_delivered', requires_review=True,
                independent_verification={'available': False, 'passed': None})


def stop_tree(process):
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    terminate_tree(process)
    # Nested evaluation workers may have their own process group on POSIX.
    for child in descendants:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(descendants, timeout=5)
    if any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in alive):
        raise RuntimeError('Worker descendants did not stop')


@dataclass
class Job:
    id: str
    request: dict
    root: Path
    state: str = 'queued'
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict | None = None
    events: list = field(default_factory=list)
    cancel_requested: bool = False
    process: subprocess.Popen | None = None
    handle: asyncio.Task | None = None
    store: TaskStore | None = None
    pid: int | None = None
    process_started_at: float | None = None
    approval: str | None = None

    def record(self):
        return {k: getattr(self, k) for k in ('id', 'request', 'state', 'created_at', 'updated_at', 'result',
                                            'cancel_requested', 'pid', 'process_started_at', 'approval')}

    def view(self):
        return {'id': self.id, **self.request, 'state': self.state, 'created_at': self.created_at,
                'updated_at': self.updated_at, 'result': self.result, 'approval': self.approval,
                'events_url': f'/tasks/{self.id}/events'}

    def transition(self, state):
        self.state, self.updated_at = state, time.time()
        self.events.append({'id': len(self.events) + 1, 'event': 'state', 'data': self.view()})
        if self.store is not None:
            self.store.save(self)


class TaskManager:
    def __init__(self, root, concurrency=1, capacity=16, timeout=240, worker_module='service.worker', retention=100):
        if concurrency < 1 or capacity < concurrency or timeout <= 0 or retention < 1:
            raise ValueError('Invalid service limits')
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.slots = asyncio.Semaphore(concurrency)
        self.capacity, self.timeout, self.worker_module = capacity, timeout, worker_module
        self.jobs = {}
        self.closing = False
        self.retention = retention
        self.store = TaskStore(self.root)
        try:
            for row in self.store.load():
                if not re.fullmatch('[0-9a-f]{32}', row['id']):
                    raise ValueError('Invalid persisted task ID')
                self.jobs[row['id']] = Job(**row, root=self.root / row['id'], store=self.store)
        except Exception:
            self.store.close()
            raise

    async def start(self):
        for job in list(self.jobs.values()):
            if job.state in {'running', 'cancelling'}:
                await asyncio.to_thread(self._stop_orphan, job)
                await asyncio.to_thread(self._clean_sandbox, job)
                self._collect_issue_partial(job, 'interrupted')
                job.transition('interrupted')
            elif job.state == 'queued':
                job.handle = asyncio.create_task(self._run(job))
        self.prune()

    @staticmethod
    def _clean_sandbox(job):
        if job.request.get('workflow') not in {'repair-approval-v1', 'issue-approval-v1'}:
            return
        from sandbox.runner import SandboxError, backend, cleanup

        if backend() == 'docker' or job.request.get('workflow') == 'issue-approval-v1':
            try:
                cleanup(job.root)
            except SandboxError as exc:
                # Keep cleanup errors observable without blocking unrelated jobs.
                (job.root / 'sandbox-cleanup-error.txt').write_text(exc.status, encoding='utf-8')

    @staticmethod
    def _collect_issue_partial(job, state):
        if job.request.get('workflow') != 'issue-approval-v1':
            return
        try:
            report = partial_issue_report(job, state)
        except (OSError, ValueError, TypeError):
            return  # A missing/partial file cannot prevent cancellation or recovery.
        if report is not None:
            keys = ('status', 'accepted', 'metrics', 'execution_mode', 'fresh_inference', 'fresh_model_calls',
                    'original_unchanged', 'public_checks_passed', 'delivery_status', 'requires_review',
                    'failure_type', 'observability', 'independent_verification', 'partial_result',
                    'engine_status', 'lifecycle_state')
            job.result = {key: report.get(key) for key in keys}

    @staticmethod
    def _stop_orphan(job):
        identity = job.root / 'worker-identity.json'
        if job.pid is None and identity.is_file():
            recorded = json.loads(identity.read_text(encoding='utf-8'))
            job.pid, job.process_started_at = recorded['pid'], recorded['process_started_at']
        if job.pid is None or job.process_started_at is None:
            return
        try:
            parent = psutil.Process(job.pid)
            if (abs(parent.create_time() - job.process_started_at) > 0.001
                    or str(job.root / 'job.json') not in parent.cmdline()):
                return
            descendants = parent.children(recursive=True)
            for process in [parent, *descendants]:
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs([parent, *descendants], timeout=5)
            if any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in alive):
                raise RuntimeError('Orphan workers did not stop')
        except psutil.NoSuchProcess:
            pass

    def prune(self):
        for task_id in self.store.prune(TERMINAL, self.retention):
            self.jobs.pop(task_id, None)

    def submit(self, request, key=None):
        if key:
            task_id = self.store.replay(key, request)
            if task_id is not None:
                return self.jobs[task_id]
        if self.closing or sum(j.state not in TERMINAL for j in self.jobs.values()) >= self.capacity:
            raise OverflowError('Task queue is full or shutting down')
        task_id = uuid.uuid4().hex
        job = Job(task_id, request, self.root / task_id)
        job.root.mkdir()
        (job.root / 'job.json').write_text(json.dumps({'request': request}), encoding='utf-8')
        job.transition('queued')
        self.store.insert(job, key)
        self.jobs[job.id] = job
        job.store = self.store
        job.handle = asyncio.create_task(self._run(job))
        return job

    def cancel(self, job):
        if job.state not in TERMINAL:
            job.cancel_requested = True
            if job.state in {'queued', 'awaiting_approval'}:
                job.transition('cancelled')
                self.prune()
            elif job.state != 'cancelling':
                job.transition('cancelling')
        return job

    def decide(self, job, decision):
        if self.closing or job.request.get('workflow') not in APPROVAL_WORKFLOWS:
            raise ValueError('Task does not accept approval decisions')
        if job.approval is not None:
            if decision != job.approval:
                raise ValueError('Task already has another approval decision')
            return job
        if job.state != 'awaiting_approval':
            raise ValueError('Task is not awaiting approval')
        job.approval = decision
        job.transition('queued')  # Persist the immutable decision before scheduling its worker.
        job.handle = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job):
        async with self.slots:
            if job.cancel_requested:
                return
            stdout, stderr = None, None
            try:
                stdout = (job.root / 'stdout.txt').open('wb')
                stderr = (job.root / 'stderr.txt').open('wb')
                env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
                env['CORECODER_SANDBOX_OWNER'] = str(job.root)
                env['CORECODER_SERVICE_TIMEOUT_SECONDS'] = str(self.timeout)
                env['CORECODER_HOME'] = str(job.root / 'corecoder-state')
                if os.environ.get('PYTHONPATH'):
                    env['PYTHONPATH'] += os.pathsep + os.environ['PYTHONPATH']
                kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
                # A resumed worker must pass its own launch handshake, never a previous worker's.
                (job.root / 'start-approved').unlink(missing_ok=True)
                (job.root / 'result.json').unlink(missing_ok=True)
                job.pid, job.process_started_at = None, None
                (job.root / 'job.json').write_text(json.dumps({'request': job.request, 'approval': job.approval}), encoding='utf-8')
                job.transition('running')
                job.process = await asyncio.to_thread(
                    subprocess.Popen, [sys.executable, '-m', 'service.launcher', self.worker_module, str(job.root / 'job.json')],
                    cwd=job.root, env=env, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, **kwargs)
                job.pid = job.process.pid
                try:
                    job.process_started_at = psutil.Process(job.pid).create_time()
                except psutil.NoSuchProcess:
                    pass
                self.store.checkpoint(job)
                if job.process_started_at is not None and not job.cancel_requested:
                    (job.root / 'start-approved').touch()
                deadline = time.monotonic() + self.timeout
                timed_out = False
                while job.process.poll() is None:
                    timed_out = time.monotonic() >= deadline
                    if job.cancel_requested or timed_out:
                        await asyncio.to_thread(stop_tree, job.process)
                        break
                    await asyncio.sleep(0.05)
                if job.cancel_requested:
                    self._collect_issue_partial(job, 'cancelled')
                    job.transition('cancelled')
                elif timed_out:
                    self._collect_issue_partial(job, 'timed_out')
                    job.transition('timed_out')
                elif job.process.returncode != 0 or not (job.root / 'result.json').is_file():
                    self._collect_issue_partial(job, 'failed')
                    job.transition('failed')
                else:
                    report = json.loads((job.root / 'result.json').read_text(encoding='utf-8'))
                    if job.request.get('workflow') in APPROVAL_WORKFLOWS and report.get('status') == 'awaiting_approval':
                        job.process = None
                        job.pid, job.process_started_at = None, None
                        job.transition('awaiting_approval')
                        return
                    if job.request.get('workflow') in APPROVAL_WORKFLOWS and report.get('status') == 'approval_rejected':
                        job.result = {'status': 'approval_rejected', 'accepted': False}
                        job.transition('rejected')
                        return
                    job.result = {k: report.get(k) for k in ('status', 'accepted', 'metrics', 'verification')}
                    if job.request.get('workflow') == 'issue-approval-v1':
                        job.result.update({k: report.get(k) for k in ('execution_mode', 'fresh_inference', 'fresh_model_calls',
                            'original_unchanged', 'public_checks_passed', 'delivery_status', 'requires_review', 'failure_type',
                            'observability')})
                        job.result.update({key: report[key] for key in
                            ('engine', 'execution_profile', 'independent_verification',
                             'pending_candidate_preserved', 'final_candidate_hash') if key in report})
                        job.result['accepted'] = False
                        if report.get('status') in {'task_timeout', 'cancelled'}:
                            state = 'timed_out' if report['status'] == 'task_timeout' else 'cancelled'
                            self._collect_issue_partial(job, state)
                            job.transition(state)
                            return
                        ready = (report.get('status') == 'public_checks_passed' and report.get('public_checks_passed') is True
                                 and report.get('delivery_status') == 'ready_for_review' and report.get('original_unchanged') is True
                                 and bool(report.get('changed_files')))
                        job.transition('ready_for_review' if ready else 'failed')
                        return
                    if job.request.get('workflow') == 'repair-approval-v1':
                        job.result.update({k: report.get(k) for k in ('execution_mode', 'fresh_inference', 'fresh_model_calls',
                                                                    'historical_usage_only', 'original_unchanged')})
                    if job.request.get('workflow') == 'tentative-approval-v1':
                        job.result.update({k: report.get(k) for k in ('publication', 'original_unchanged', 'task_end_sha256',
                                                                    'failure_type')})
                    accepted = (report.get('accepted') is True and report.get('status') == 'passed'
                                and (report.get('verification') or {}).get('passed') is True)
                    job.result['accepted'] = accepted
                    job.transition('succeeded' if accepted else 'failed')
            except Exception:  # noqa: BLE001 - preserve task state without exposing worker credentials or logs
                if job.process is not None and job.process.poll() is None:
                    await asyncio.to_thread(stop_tree, job.process)
                self._collect_issue_partial(job, 'cancelled' if job.cancel_requested else 'failed')
                job.transition('cancelled' if job.cancel_requested else 'failed')
            finally:
                await asyncio.to_thread(self._clean_sandbox, job)
                for stream in (stdout, stderr):
                    if stream is not None:
                        stream.close()
                self.prune()

    async def close(self):
        self.closing = True
        jobs = list(self.jobs.values())
        for job in jobs:
            if job.state != 'awaiting_approval':
                self.cancel(job)
        await asyncio.gather(*(j.handle for j in jobs if j.handle is not None))
        self.store.close()
