"""Local FastAPI task submission, polling, lifecycle SSE, and cancellation."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from evals.schema import load_suite
from service.manager import ROOT, TERMINAL, TaskManager
from service.worker import SUITES


class SubmitTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suite: Literal['smoke', 'localization'] = 'smoke'
    task_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,79}$')
    mode: Literal['scripted', 'unchanged', 'reference', 'live'] = 'scripted'
    search_backend: Literal['off', 'none', 'keyword'] = 'off'
    workflow: Literal['langgraph-v1', 'langgraph-approval-v1'] | None = None


class TaskView(SubmitTask):
    id: str
    state: Literal['queued', 'running', 'awaiting_approval', 'cancelling', 'succeeded', 'failed', 'rejected',
                   'cancelled', 'timed_out', 'interrupted']
    approval: Literal['approve', 'reject'] | None = None
    created_at: float
    updated_at: float
    result: dict | None
    events_url: str


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approve', 'reject']


def create_app(output=None, concurrency=1, capacity=16, timeout=240, worker_module='service.worker', retention=100):
    @asynccontextmanager
    async def lifespan(app):
        app.state.manager = TaskManager(output or ROOT / '.tmp/service', concurrency, capacity, timeout, worker_module, retention)
        try:
            await app.state.manager.start()
            yield
        finally:
            await app.state.manager.close()

    app = FastAPI(title='CoreCoder Local Repair Service', version='0.2.0', lifespan=lifespan)

    def job_or_404(task_id):
        job = app.state.manager.jobs.get(task_id)
        if job is None:
            raise HTTPException(404, 'Unknown task')
        return job

    @app.get('/health')
    async def health():
        return {'status': 'ok'}

    @app.get('/catalog')
    async def catalog():
        return {name: [{'task_id': t.task_id, 'title': t.title} for t in load_suite(path)] for name, path in SUITES.items()}

    @app.post('/tasks', status_code=202, response_model=TaskView)
    async def submit(body: SubmitTask, idempotency_key: str | None = Header(default=None)):
        if idempotency_key is not None and not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', idempotency_key):
            raise HTTPException(400, 'Invalid Idempotency-Key')
        if body.workflow is not None and find_spec('langgraph') is None:
            raise HTTPException(503, 'Install the workflow extra to use langgraph-v1')
        if body.workflow == 'langgraph-approval-v1' and find_spec('langgraph.checkpoint.sqlite') is None:
            raise HTTPException(503, 'Install the workflow extra for persistent approval')
        try:
            load_suite(SUITES[body.suite], [body.task_id])
        except ValueError as exc:
            raise HTTPException(422, 'Unknown task in the selected suite') from exc
        try:
            job = app.state.manager.submit(body.model_dump(exclude_none=True), idempotency_key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(410, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        return job.view()

    @app.get('/tasks/{task_id}', response_model=TaskView)
    async def status(task_id: str):
        return job_or_404(task_id).view()

    @app.post('/tasks/{task_id}/cancel', response_model=TaskView)
    async def cancel(task_id: str):
        return app.state.manager.cancel(job_or_404(task_id)).view()

    @app.post('/tasks/{task_id}/approval', status_code=202, response_model=TaskView)
    async def approve(task_id: str, body: ApprovalDecision):
        try:
            return app.state.manager.decide(job_or_404(task_id), body.decision).view()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/tasks/{task_id}/artifacts/{name}')
    async def artifact(task_id: str, name: str):
        job = job_or_404(task_id)
        if name == 'workflow.json':
            path = job.root / name
            if not path.is_file() or path.is_symlink():
                raise HTTPException(404, 'No workflow snapshot available')
            return FileResponse(path, filename=name, media_type='application/json')
        if name not in {'patch.diff', 'report.json'}:
            raise HTTPException(404, 'Unknown artifact')
        if job.state not in {'succeeded', 'failed'} or job.result is None:
            raise HTTPException(409, 'No completed report available')
        report = json.loads((job.root / 'result.json').read_text(encoding='utf-8'))
        location = (Path(report['artifacts']) / name).resolve()
        if not location.is_relative_to((job.root / 'runs').resolve()) or not location.is_file() or location.is_symlink():
            raise HTTPException(404, 'Unknown artifact')
        return FileResponse(location, filename=name, media_type='text/plain' if name == 'patch.diff' else 'application/json')

    @app.get('/tasks/{task_id}/events')
    async def events(task_id: str, request: Request, last_event_id: str | None = Header(default=None)):
        job = job_or_404(task_id)
        try:
            cursor = int(last_event_id or '0')
            if not 0 <= cursor <= len(job.events):
                raise ValueError('Invalid cursor')
        except ValueError as exc:
            raise HTTPException(400, 'Invalid Last-Event-ID') from exc

        async def stream():
            nonlocal cursor
            heartbeat = 0
            while True:
                for event in job.events[cursor:]:
                    cursor = event['id']
                    yield f"id: {cursor}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                if job.state in TERMINAL or await request.is_disconnected():
                    return
                heartbeat += 1
                if heartbeat % 50 == 0:
                    yield ': keepalive\n\n'
                await asyncio.sleep(0.1)

        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return app
